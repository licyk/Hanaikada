"""The background scanner: one thread, a priority queue of jobs.

Highest priority first: files a listing or the viewer asked for, then folders a user is looking at,
then whole roots, then thumbnail pre-generation. A folder is re-listed only when its mtime differs
from the stored one (or it has none); a file is re-read only when its size or mtime differs from
its row. A full scan ignores both. Errors are per file: counted, recorded in ``parse_error``, never
fatal to the scan.
"""

import heapq
import itertools
import logging
import os
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

from hanaikada.core.errors import HanaikadaError
from hanaikada.core.events.models import ScanCompletedEvent, ScanFailedEvent, ScanProgressEvent, ScanStartedEvent
from hanaikada.core.index.models import RootScanState
from hanaikada.core.library.layouts import is_ignored_name
from hanaikada.core.library.safety import resolve_in_root

if TYPE_CHECKING:
    from hanaikada.core.index.service import IndexService

logger = logging.getLogger(__name__)

PRIORITY_FILES = 0
PRIORITY_FOLDER = 10
PRIORITY_ROOT = 20
PRIORITY_REPARSE = 25
PRIORITY_THUMBS = 40
BATCH_SIZE = 50
PROGRESS_INTERVAL = 0.25


@dataclass
class Job:
    kind: str
    root_id: str | None
    rel: str = ""
    full: bool = False
    recursive: bool = True
    rels: list[str] = field(default_factory=list)

    @property
    def key(self) -> tuple[str, str | None, str, bool]:
        return (self.kind, self.root_id, self.rel, self.full)


class ScanCancelled(Exception):
    pass


@dataclass
class _Counts:
    folders_seen: int = 0
    files_seen: int = 0
    files_indexed: int = 0
    files_failed: int = 0
    files_missing: int = 0


class Scanner:
    def __init__(self, index: "IndexService") -> None:
        self.index = index
        self._heap: list[tuple[int, int, Job]] = []
        self._keys: set[tuple[str, str | None, str, bool]] = set()
        self._seq = itertools.count()
        self._cond = threading.Condition()
        self._thread: threading.Thread | None = None
        self._stop = False
        self._cancel = threading.Event()
        self.current: Job | None = None
        self.states: dict[str, RootScanState] = {}
        self._last_watch = time.monotonic()
        self._last_progress = 0.0

    # -- queue ---------------------------------------------------------------

    def start(self) -> None:
        if self._thread is not None:
            return
        self._stop = False
        self._thread = threading.Thread(target=self._run, name="hanaikada-scanner", daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 10.0) -> None:
        with self._cond:
            self._stop = True
            self._cancel.set()
            self._cond.notify_all()
        if self._thread is not None:
            self._thread.join(timeout)
            self._thread = None

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def submit(self, job: Job, priority: int) -> bool:
        """Queue a job unless an identical one is waiting. File jobs for one root are merged."""
        with self._cond:
            if job.kind == "files":
                for _, _, queued in self._heap:
                    if queued.kind == "files" and queued.root_id == job.root_id:
                        known = set(queued.rels)
                        queued.rels.extend(r for r in job.rels if r not in known)
                        return True
            elif job.key in self._keys:
                return False
            self._keys.add(job.key)
            heapq.heappush(self._heap, (priority, next(self._seq), job))
            if job.kind == "root" and job.root_id is not None:
                state = self.states.setdefault(job.root_id, RootScanState(root_id=job.root_id))
                if state.state != "scanning":
                    state.state = "queued"
                    state.full = job.full
            self._cond.notify_all()
        return True

    def queued(self) -> list[Job]:
        with self._cond:
            return [job for _, _, job in sorted(self._heap)]

    def pending(self) -> int:
        with self._cond:
            return len(self._heap)

    def is_busy_with_full(self, root_id: str) -> bool:
        with self._cond:
            current = self.current
            waiting = any(j.kind == "root" and j.full and j.root_id == root_id for _, _, j in self._heap)
        return waiting or (current is not None and current.kind == "root" and current.full and current.root_id == root_id)

    def cancel(self) -> int:
        """Drop every queued scan and stop the running one at the next file."""
        with self._cond:
            dropped = [job for _, _, job in self._heap if job.kind in ("root", "folder", "reparse", "thumbs")]
            self._heap = [entry for entry in self._heap if entry[2].kind not in ("root", "folder", "reparse", "thumbs")]
            heapq.heapify(self._heap)
            for job in dropped:
                self._keys.discard(job.key)
                if job.kind == "root" and job.root_id in self.states and self.states[job.root_id].state == "queued":
                    self.states[job.root_id].state = "idle"
            if self.current is not None and self.current.kind != "files":
                self._cancel.set()
        return len(dropped)

    def wait_idle(self, timeout: float | None = None) -> bool:
        """Block until the queue is empty and no job runs. For tests and the command line."""
        deadline = None if timeout is None else time.monotonic() + timeout
        with self._cond:
            while self._heap or self.current is not None:
                remaining = None if deadline is None else deadline - time.monotonic()
                if remaining is not None and remaining <= 0:
                    return False
                self._cond.wait(remaining if remaining is not None else 0.5)
        return True

    def _next(self) -> Job | None:
        with self._cond:
            while not self._heap and not self._stop:
                interval = self.index.settings.settings.index.watch_interval
                timeout = None if interval <= 0 else max(0.5, interval - (time.monotonic() - self._last_watch))
                self._cond.wait(timeout if timeout is not None else 5.0)
                if not self._heap and interval > 0 and time.monotonic() - self._last_watch >= interval:
                    self._last_watch = time.monotonic()
                    return Job("watch", None)
            if self._stop:
                return None
            _, _, job = heapq.heappop(self._heap)
            self._keys.discard(job.key)
            self.current = job
            self._cancel.clear()
            return job

    def _run(self) -> None:
        while True:
            job = self._next()
            if job is None:
                return
            try:
                self.run_job(job)
            except Exception:
                logger.exception("Scanner job %s failed", job.kind)
            finally:
                with self._cond:
                    self.current = None
                    self._cond.notify_all()

    # -- jobs ------------------------------------------------------------------

    def run_job(self, job: Job) -> None:
        if job.kind == "files" and job.root_id is not None:
            self.index.index_files(job.root_id, job.rels)
        elif job.kind == "root" and job.root_id is not None:
            self.scan_root(job.root_id, job.full)
        elif job.kind == "folder" and job.root_id is not None:
            self.scan_tree(job.root_id, job.rel, job.full, job.recursive, _Counts(), publish=False)
        elif job.kind == "reparse":
            self.index.reparse(job.root_id, cancel=self._cancel)
        elif job.kind == "thumbs" and job.root_id is not None:
            self.index.pregenerate_thumbnails(job.root_id, job.rels, cancel=self._cancel)
        elif job.kind == "watch":
            self.watch()

    def _check_cancel(self) -> None:
        if self._cancel.is_set():
            raise ScanCancelled

    def _progress(self, root_id: str, counts: _Counts, current: str | None, force: bool = False) -> None:
        state = self.states.setdefault(root_id, RootScanState(root_id=root_id))
        state.folders_seen, state.files_seen = counts.folders_seen, counts.files_seen
        state.files_indexed, state.files_failed, state.current = counts.files_indexed, counts.files_failed, current
        now = time.monotonic()
        if force or now - self._last_progress >= PROGRESS_INTERVAL:
            self._last_progress = now
            self.index.events.publish(
                ScanProgressEvent(
                    root_id=root_id,
                    folders_seen=counts.folders_seen,
                    files_seen=counts.files_seen,
                    files_indexed=counts.files_indexed,
                    files_failed=counts.files_failed,
                    current=current,
                )
            )

    def scan_root(self, root_id: str, full: bool) -> None:
        index = self.index
        try:
            root = index.library.root(root_id)
        except HanaikadaError:
            self.states.pop(root_id, None)
            return
        state = self.states.setdefault(root_id, RootScanState(root_id=root_id))
        state.state, state.full, state.error = "scanning", full, None
        state.started_at, state.finished_at = datetime.now(timezone.utc), None
        counts = _Counts()
        index.events.publish(ScanStartedEvent(root_id=root_id, full=full))
        cancelled = False
        try:
            if not root.enabled or not root.index:
                return
            plan = index.library.plan(root_id)
            for output in plan.outputs:
                self.scan_tree(root_id, output.rel, full, True, counts, publish=True)
            counts.files_missing = index.reconcile(root_id)
            index.after_root_scan(root_id, plan)
        except ScanCancelled:
            cancelled = True
        except Exception as e:
            logger.exception("Scan of root %s failed", root_id)
            state.state, state.error = "failed", str(e)
            state.finished_at = datetime.now(timezone.utc)
            index.events.publish(ScanFailedEvent(root_id=root_id, files_indexed=counts.files_indexed, error=str(e)))
            return
        finally:
            if state.state != "failed":
                state.state = "idle"
                state.current = None
                state.finished_at = datetime.now(timezone.utc)
        self._progress(root_id, counts, None, force=True)
        index.events.publish(
            ScanCompletedEvent(
                root_id=root_id,
                folders_seen=counts.folders_seen,
                files_seen=counts.files_seen,
                files_indexed=counts.files_indexed,
                files_failed=counts.files_failed,
                files_missing=counts.files_missing,
                cancelled=cancelled,
            )
        )

    def scan_tree(self, root_id: str, start: str, full: bool, recursive: bool, counts: _Counts, publish: bool) -> None:
        """Walk a folder tree, re-listing the folders that changed and indexing the files that did."""
        index = self.index
        library = index.library
        root_path = library.root_path(root_id)
        plan = library.plan(root_id)
        follow = library.follow_symlinks
        images = library.image_extensions
        seen: set[tuple[int, int]] = set()
        stack = [start]
        new_files: list[str] = []
        while stack:
            self._check_cancel()
            rel = stack.pop()
            if not plan.dir_indexed(rel):
                continue
            try:
                path = resolve_in_root(root_path, rel, follow_symlinks=follow)
                st = path.stat()
            except (OSError, HanaikadaError):
                index.forget_folder(root_id, rel)
                continue
            if (st.st_dev, st.st_ino) in seen:
                continue
            seen.add((st.st_dev, st.st_ino))
            counts.folders_seen += 1
            stored = index.folder_mtime(root_id, rel)
            if full or stored is None or stored != st.st_mtime_ns:
                subdirs, files = self._list(path, rel, plan, images)
                counts.files_seen += len(files)
                changed = index.stale_files(root_id, rel, {name: (fst.st_size, fst.st_mtime_ns) for name, fst in files.items()}, full)
                names = set(files)
                siblings = {entry for entry in os.listdir(path)} if changed else set()
                for batch_start in range(0, len(changed), BATCH_SIZE):
                    self._check_cancel()
                    batch = changed[batch_start : batch_start + BATCH_SIZE]
                    self._progress(root_id, counts, f"{rel}/{batch[0]}" if rel else batch[0])
                    ok, failed = index.index_batch(root_id, rel, [(name, path / name, files[name]) for name in batch], siblings)
                    counts.files_indexed += ok
                    counts.files_failed += failed
                    new_files.extend(f"{rel}/{name}" if rel else name for name in batch)
                index.missing_in_dir(root_id, rel, names)
                index.set_folder(root_id, rel, st.st_mtime_ns, subdirs)
            else:
                subdirs = index.known_subfolders(root_id, rel)
            if publish:
                self._progress(root_id, counts, rel or None)
            if recursive:
                stack.extend(sorted(subdirs, reverse=True))
        if new_files and index.settings.settings.thumbnails.pregenerate and self.running:
            self.submit(Job("thumbs", root_id, rel=f"{start}#{time.monotonic()}", rels=new_files), PRIORITY_THUMBS)

    @staticmethod
    def _list(path: Path, rel: str, plan, images: set[str]) -> tuple[list[str], dict[str, os.stat_result]]:  # type: ignore[no-untyped-def]
        subdirs: list[str] = []
        files: dict[str, os.stat_result] = {}
        try:
            iterator = os.scandir(path)
        except OSError:
            return subdirs, files
        with iterator as it:
            for entry in it:
                if is_ignored_name(entry.name):
                    continue
                child = f"{rel}/{entry.name}" if rel else entry.name
                try:
                    if entry.is_dir(follow_symlinks=True):
                        if plan.dir_indexed(child):
                            subdirs.append(child)
                        continue
                    if os.path.splitext(entry.name)[1].lower() in images and plan.file_visible(entry.name):
                        files[entry.name] = entry.stat(follow_symlinks=True)
                except OSError:
                    continue
        return subdirs, files

    def watch(self) -> None:
        """Stat every known folder of every indexed root and queue the ones that changed."""
        index = self.index
        for root in index.library.list_roots():
            if not (root.enabled and root.index and root.exists):
                continue
            try:
                root_path = index.library.root_path(root.id)
            except HanaikadaError:
                continue
            for rel, stored in index.folders_of(root.id):
                try:
                    current = resolve_in_root(root_path, rel, follow_symlinks=index.library.follow_symlinks).stat().st_mtime_ns
                except (OSError, HanaikadaError):
                    current = None
                if current != stored:
                    self.submit(Job("folder", root.id, rel=rel, recursive=current is None), PRIORITY_FOLDER)
