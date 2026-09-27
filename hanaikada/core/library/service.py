"""The library: roots, live folder listings, thumbnails and file operations.

Listings are live: the folder is read with ``scandir`` and joined with the index rows for that
folder, so a new file appears at once — marked ``indexed: false`` and queued for indexing ahead of
the background scan — and a file deleted outside the application disappears at once too. Every
operation here updates the index in the same call, so the index never has to discover what the
application itself did.
"""

import io
import logging
import os
import random
import subprocess
import sys
import threading
import time
import uuid
import zipfile
from collections import Counter
from collections.abc import Iterator
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, BinaryIO, cast

from hanaikada.core.errors import ConflictError, HanaikadaError, InvalidPathError, NotFoundError, ValidationError
from hanaikada.core.events import EventBus
from hanaikada.core.events.models import ImportProgressEvent, LibraryChangedEvent
from hanaikada.core.library.companions import invokeai_thumbnail, sidecars_of
from hanaikada.core.library.fsops import copy_path, move_path, remove_path, rename_no_overwrite
from hanaikada.core.library.layouts import LayoutPlan, detect_layout, is_ignored_name, plan_for
from hanaikada.core.library.models import (
    COMBINED_VIEW_ID,
    CombinedFolder,
    CombinedListing,
    CoverImage,
    DeleteRequest,
    EntryKind,
    FileEntry,
    FolderCreate,
    FolderEntry,
    FolderListing,
    LayoutSuggestion,
    ListSort,
    OpenRequest,
    OperationError,
    OperationResult,
    PathRef,
    RenameRequest,
    RootCreate,
    RootInfo,
    RootUpdate,
    ThumbnailCacheInfo,
    TransferRequest,
    TreeNode,
)
from hanaikada.core.library.safety import escapes_root, resolve_in_root, split_rel, to_rel, unique_path, validate_name
from hanaikada.core.library.thumbnails import Thumbnail, ThumbnailService
from hanaikada.core.settings import ImageRoot, SettingsService
from hanaikada.core.settings.models import LayoutName

if TYPE_CHECKING:
    from hanaikada.core.index.service import IndexService

logger = logging.getLogger(__name__)

VIDEO_EXTENSIONS = {".mp4", ".webm", ".mkv", ".mov", ".avi", ".m4v"}
AUDIO_EXTENSIONS = {".mp3", ".flac", ".wav", ".ogg", ".opus", ".m4a", ".aac"}
PLAN_TTL = 30.0
COVER_SIZE = 4


def _join(rel_dir: str, name: str) -> str:
    return f"{rel_dir}/{name}" if rel_dir else name


def _parent(rel: str) -> str:
    return rel.rsplit("/", 1)[0] if "/" in rel else ""


def _ctime_ns(st: os.stat_result) -> int | None:
    birth = getattr(st, "st_birthtime_ns", None)
    if birth is not None:
        return birth
    birth_s = getattr(st, "st_birthtime", None)
    if birth_s is not None:
        return int(birth_s * 1e9)
    return st.st_ctime_ns if sys.platform == "win32" else None


# Folder names that say nothing on their own: an install's "core", an "outputs" folder.
GENERIC_FOLDER_NAMES = {"core", "app", "webui", "output", "outputs", "images", "src"}


def default_root_name(path: Path) -> str:
    """``/srv/stable-diffusion-webui/core`` → ``stable-diffusion-webui``: a generic name takes its parent's."""
    name = path.name or str(path)
    if name.lower() in GENERIC_FOLDER_NAMES and path.parent.name:
        return path.parent.name
    return name


class UploadWriter:
    """Streams an upload into ``<name>.part`` beside the target, then renames it into place."""

    def __init__(self, service: "LibraryService", root_id: str, target: Path, total: int | None) -> None:
        self._service = service
        self.root_id = root_id
        self.target = target
        self.part = target.with_name(target.name + ".part")
        self.total = total
        self.written = 0
        self._last_event = 0.0
        try:
            # Held open across write() calls and closed in commit() or abort().
            self._file: BinaryIO = open(self.part, "xb")  # noqa: SIM115
        except FileExistsError:
            raise ConflictError(f"An upload of {target.name} is already in progress") from None

    def write(self, chunk: bytes) -> None:
        self._file.write(chunk)
        self.written += len(chunk)
        now = time.monotonic()
        if now - self._last_event >= 0.25:
            self._last_event = now
            self._publish(done=False)

    def _publish(self, done: bool) -> None:
        root_path = self._service.root_path(self.root_id)
        self._service.events.publish(ImportProgressEvent(root_id=self.root_id, rel_path=to_rel(root_path, self.target), bytes_done=self.written, total_bytes=self.total, done=done))

    def commit(self) -> PathRef:
        self._file.close()
        if self.total is not None and self.written != self.total:
            self.abort()
            raise ValidationError(f"Upload incomplete: received {self.written} of {self.total} bytes")
        try:
            rename_no_overwrite(self.part, self.target)
        except BaseException:
            self.abort()
            raise
        self._publish(done=True)
        root_path = self._service.root_path(self.root_id)
        rel = to_rel(root_path, self.target)
        self._service.after_created(self.root_id, [rel], index_now=True)
        return PathRef(root_id=self.root_id, path=rel)

    def abort(self) -> None:
        if not self._file.closed:
            self._file.close()
        try:
            self.part.unlink()
        except FileNotFoundError:
            pass


class _ZipStream(io.RawIOBase):
    """A write-only sink zipfile can write into while the caller drains it chunk by chunk."""

    def __init__(self) -> None:
        self._chunks: list[bytes] = []
        self._position = 0

    def writable(self) -> bool:
        return True

    def write(self, data: Any) -> int:
        chunk = bytes(data)
        self._chunks.append(chunk)
        self._position += len(chunk)
        return len(chunk)

    def tell(self) -> int:
        return self._position

    def drain(self) -> bytes:
        out = b"".join(self._chunks)
        self._chunks.clear()
        return out


class LibraryService:
    def __init__(self, settings: SettingsService, events: EventBus, thumbnails: ThumbnailService, roots_locked: bool = False) -> None:
        """``roots_locked`` is for a host application that supplies the image folders itself: they
        cannot then be added, changed or removed, and the interface hides those actions."""
        self.settings = settings
        self.events = events
        self.thumbnails = thumbnails
        self.roots_locked = roots_locked
        self.index: IndexService | None = None
        self._plans: dict[tuple[str, str, str, bool], tuple[float, LayoutPlan]] = {}
        self._plans_lock = threading.Lock()
        self._covers: dict[tuple[str, str], tuple[int, list[CoverImage]]] = {}
        settings.on_change(lambda _s: self.forget_plans())

    # -- roots --------------------------------------------------------------

    def _roots(self) -> list[ImageRoot]:
        return list(self.settings.settings.paths.roots)

    def root(self, root_id: str) -> ImageRoot:
        for root in self._roots():
            if root.id == root_id:
                return root
        raise NotFoundError(f"No root with id {root_id!r}")

    def root_path(self, root_id: str) -> Path:
        return Path(self.root(root_id).path).expanduser().resolve()

    def forget_plans(self) -> None:
        with self._plans_lock:
            self._plans.clear()

    def plan(self, root_id: str) -> LayoutPlan:
        """The layout's view of a root, recomputed at most every half minute or on a settings change."""
        root = self.root(root_id)
        key = (root.id, root.layout, root.path, self.settings.settings.index.include_comfyui_temp)
        now = time.monotonic()
        with self._plans_lock:
            hit = self._plans.get(key)
            if hit is not None and now - hit[0] < PLAN_TTL:
                return hit[1]
        plan = plan_for(root.layout, self.root_path(root_id), self.settings.settings.index.include_comfyui_temp)
        with self._plans_lock:
            self._plans[key] = (now, plan)
        return plan

    def _info(self, root: ImageRoot) -> RootInfo:
        path = Path(root.path).expanduser()
        exists = path.is_dir()
        outputs: list[str] = []
        if exists:
            try:
                outputs = [o.rel for o in self.plan(root.id).outputs]
            except OSError:
                outputs = []
        return RootInfo(id=root.id, name=root.name, path=root.path, layout=root.layout, enabled=root.enabled, index=root.index, exists=exists, outputs=outputs)

    def list_roots(self) -> list[RootInfo]:
        return [self._info(r) for r in self._roots()]

    def get_root(self, root_id: str) -> RootInfo:
        return self._info(self.root(root_id))

    def _check_roots_unlocked(self) -> None:
        if self.roots_locked:
            raise ConflictError("The image folders are fixed by the application that started Hanaikada and cannot be changed here.")

    @staticmethod
    def suggest_layout(path: str) -> LayoutSuggestion:
        folder = Path(path).expanduser()
        if not folder.is_dir():
            raise NotFoundError(f"Not a directory: {folder}")
        layout, reason = detect_layout(folder.resolve())
        return LayoutSuggestion(layout=cast(LayoutName, layout), reason=reason)

    def add_root(self, req: RootCreate, *, root_id: str | None = None) -> RootInfo:
        self._check_roots_unlocked()
        path = Path(req.path).expanduser()
        if not path.is_absolute():
            raise InvalidPathError("A root path must be absolute")
        path = path.resolve()
        if not path.is_dir():
            raise NotFoundError(f"Not a directory: {path}")
        if root_id == COMBINED_VIEW_ID:
            raise ValidationError(f"{COMBINED_VIEW_ID!r} is reserved for the combined view and cannot be a root id")
        for existing in self._roots():
            if root_id is not None and existing.id == root_id:
                raise ConflictError(f"Already a root with id {root_id!r}")
            if Path(existing.path).expanduser().resolve() == path:
                raise ConflictError(f"Already a root: {path}", {"root_id": existing.id})
        layout = cast(LayoutName, req.layout if req.layout != "auto" else detect_layout(path)[0])
        root = ImageRoot(id=root_id or uuid.uuid4().hex[:8], name=req.name or default_root_name(path), path=str(path), layout=layout, enabled=req.enabled, index=req.index)

        def add(data: dict[str, Any]) -> None:
            data["paths"]["roots"].append(root.model_dump())

        self.settings.mutate(add)
        if self.index is not None and root.enabled and root.index:
            self.index.queue_root(root.id, full=False)
        return self._info(root)

    def update_root(self, root_id: str, req: RootUpdate) -> RootInfo:
        self._check_roots_unlocked()
        before = self.root(root_id)
        changes = req.model_dump(exclude_none=True)
        if "path" in changes:
            path = Path(changes["path"]).expanduser()
            if not path.is_absolute() or not path.is_dir():
                raise InvalidPathError(f"Not an absolute directory: {path}")
            changes["path"] = str(path.resolve())

        def update(data: dict[str, Any]) -> None:
            for r in data["paths"]["roots"]:
                if r["id"] == root_id:
                    r.update(changes)

        self.settings.mutate(update)
        after = self.root(root_id)
        if self.index is not None:
            if after.path != before.path or after.layout != before.layout:
                self.index.forget_root(root_id)
            if after.enabled and after.index and (not (before.enabled and before.index) or after.path != before.path or after.layout != before.layout):
                self.index.queue_root(root_id, full=False)
        return self.get_root(root_id)

    def remove_root(self, root_id: str) -> None:
        """Forget a root and its index rows. Files on disk are untouched."""
        self._check_roots_unlocked()
        self.root(root_id)

        def remove(data: dict[str, Any]) -> None:
            data["paths"]["roots"] = [r for r in data["paths"]["roots"] if r["id"] != root_id]

        self.settings.mutate(remove)
        if self.index is not None:
            self.index.forget_root(root_id)

    def locate(self, path: Path) -> PathRef:
        """Find the root that contains an absolute path.

        The path as written is tried first, so a path that runs through a symlinked folder inside
        a root is found there rather than where it really lives.
        """
        given = Path(os.path.abspath(path.expanduser()))
        candidates = [given, given.resolve()] if self.follow_symlinks else [given.resolve()]
        for target in candidates:
            best: tuple[str, Path] | None = None
            for root in self._roots():
                root_path = Path(root.path).expanduser()
                root_path = root_path if target is given else root_path.resolve()
                if (target == root_path or root_path in target.parents) and (best is None or len(str(root_path)) > len(str(best[1]))):
                    best = (root.id, root_path)
            if best is not None:
                return PathRef(root_id=best[0], path=to_rel(best[1], target))
        raise NotFoundError(f"{given} is not inside any root")

    def notify_changed(self, root_id: str, rel_path: str) -> None:
        self.events.publish(LibraryChangedEvent(root_id=root_id, rel_path=rel_path))

    # -- resolving ----------------------------------------------------------

    @property
    def follow_symlinks(self) -> bool:
        return self.settings.settings.index.follow_symlinks

    @property
    def image_extensions(self) -> set[str]:
        return {e.lower() for e in self.settings.settings.index.image_extensions}

    def kind_of(self, name: str) -> EntryKind:
        ext = os.path.splitext(name)[1].lower()
        if ext in self.image_extensions:
            return "image"
        if ext in VIDEO_EXTENSIONS:
            return "video"
        if ext in AUDIO_EXTENSIONS:
            return "audio"
        return "file"

    def resolve(self, root_id: str, rel_path: str, must_exist: bool = True, kind: str | None = None) -> tuple[ImageRoot, Path, Path, str]:
        """``(root, root_path, target, rel)`` for a client path, refusing anything the layout hides.

        ``kind`` is ``"dir"`` or ``"file"`` when the target must be one.
        """
        root = self.root(root_id)
        root_path = self.root_path(root_id)
        if not root_path.is_dir():
            raise NotFoundError(f"Root folder is missing: {root_path}")
        parts = split_rel(rel_path)
        rel = "/".join(parts)
        target = resolve_in_root(root_path, rel, follow_symlinks=self.follow_symlinks)
        plan = self.plan(root_id)
        exists = target.exists()
        is_dir = target.is_dir() if exists else kind == "dir"
        visible_dir = rel if is_dir else _parent(rel)
        if not plan.dir_visible(visible_dir):
            raise NotFoundError(f"Not found: {rel_path}")
        if not is_dir and parts and not self._file_allowed(plan, visible_dir, parts[-1]):
            raise NotFoundError(f"Not found: {rel_path}")
        if must_exist and not exists:
            raise NotFoundError(f"Not found: {rel_path}")
        if must_exist and kind == "dir" and not is_dir:
            raise InvalidPathError(f"Not a folder: {rel_path}")
        if must_exist and kind == "file" and not target.is_file():
            raise InvalidPathError(f"Not a file: {rel_path}")
        return root, root_path, target, rel

    def _file_allowed(self, plan: LayoutPlan, rel_dir: str, name: str) -> bool:
        """Files are shown only inside output folders, and only media unless ``library.show_all_files``."""
        if plan.output_of(rel_dir) is None or not plan.file_visible(name):
            return False
        return self.kind_of(name) != "file" or self.settings.settings.library.show_all_files or os.path.splitext(name)[1].lower() in self._sidecar_extensions

    @property
    def _sidecar_extensions(self) -> set[str]:
        return {e.lower() for e in self.settings.settings.library.sidecar_extensions}

    def _link_allowed(self, root_path: Path, path: Path) -> bool:
        """Hide what a link leads outside the root while links are not followed."""
        if self.follow_symlinks or not path.is_symlink():
            return True
        return not escapes_root(root_path, path)

    # -- listing ------------------------------------------------------------

    def _scan_folder(
        self, root_path: Path, target: Path, rel: str, plan: LayoutPlan
    ) -> tuple[list[tuple[os.DirEntry[str], os.stat_result]], list[tuple[os.DirEntry[str], os.stat_result]]]:
        folders: list[tuple[os.DirEntry[str], os.stat_result]] = []
        files: list[tuple[os.DirEntry[str], os.stat_result]] = []
        show_all = self.settings.settings.library.show_all_files
        in_output = plan.output_of(rel) is not None
        try:
            iterator = os.scandir(target)
        except OSError as e:
            raise NotFoundError(f"Cannot read {rel or 'the root'}: {e.strerror}") from e
        with iterator as it:
            for entry in it:
                if is_ignored_name(entry.name):
                    continue
                try:
                    is_dir = entry.is_dir(follow_symlinks=True)
                    st = entry.stat(follow_symlinks=True)
                except OSError:
                    continue
                child = _join(rel, entry.name)
                if is_dir:
                    if plan.dir_visible(child) and self._link_allowed(root_path, Path(entry.path)):
                        folders.append((entry, st))
                elif in_output and plan.file_visible(entry.name) and (show_all or self.kind_of(entry.name) != "file") and self._link_allowed(root_path, Path(entry.path)):
                    files.append((entry, st))
        return folders, files

    @staticmethod
    def _sort_key(sort: ListSort, st: os.stat_result, name: str) -> Any:
        if sort == "mtime":
            return (st.st_mtime_ns, name)
        if sort == "ctime":
            return (_ctime_ns(st) or st.st_mtime_ns, name)
        if sort == "size":
            return (st.st_size, name)
        return (name.lower(), name)

    def list_entries(
        self,
        root_id: str,
        rel_path: str = "",
        sort: ListSort = "mtime",
        descending: bool = True,
        cursor: str | None = None,
        limit: int = 500,
        random_seed: int | None = None,
    ) -> FolderListing:
        """One folder: its visible subfolders (first page only) and a page of its files.

        Files the index does not know yet, or knows at an older size or mtime, come back with
        ``indexed: false`` and are queued for indexing ahead of the background scan.
        """
        _, root_path, target, rel = self.resolve(root_id, rel_path, kind="dir")
        plan = self.plan(root_id)
        folder_entries, file_entries = self._scan_folder(root_path, target, rel, plan)
        if sort == "random":
            rng = random.Random(random_seed or 0)
            file_entries.sort(key=lambda e: e[0].name)
            rng.shuffle(file_entries)
        else:
            file_entries.sort(key=lambda e: self._sort_key(sort, e[1], e[0].name), reverse=descending)
        folder_entries.sort(key=lambda e: e[0].name.lower())

        offset = 0
        if cursor:
            try:
                offset = max(0, int(cursor))
            except ValueError:
                raise ValidationError("Invalid cursor") from None
        page = file_entries[offset : offset + limit]
        next_cursor = str(offset + limit) if offset + limit < len(file_entries) else None

        rows = self.index.rows_for_dir(root_id, rel) if self.index is not None else {}
        present = {entry.name for entry, _ in file_entries}
        stale: list[str] = []
        files: list[FileEntry] = []
        for entry, st in page:
            kind = self.kind_of(entry.name)
            child = _join(rel, entry.name)
            record = rows.get(entry.name)
            fresh = record is not None and record.size == st.st_size and record.version == str(st.st_mtime_ns)
            if kind == "image" and not fresh:
                stale.append(child)
            ctime = _ctime_ns(st)
            files.append(
                FileEntry(
                    name=entry.name,
                    path=child,
                    kind=kind,
                    size=st.st_size,
                    mtime=datetime.fromtimestamp(st.st_mtime_ns / 1e9, tz=timezone.utc),
                    ctime=datetime.fromtimestamp(ctime / 1e9, tz=timezone.utc) if ctime else None,
                    version=str(st.st_mtime_ns),
                    indexed=fresh,
                    image=record,
                )
            )
        if self.index is not None:
            gone = [_join(rel, name) for name, record in rows.items() if name not in present and not record.missing]
            if gone:
                self.index.mark_missing(root_id, gone)
            if stale:
                self.index.queue_files(root_id, stale)

        folders: list[FolderEntry] = []
        if offset == 0:
            for entry, st in folder_entries:
                child = _join(rel, entry.name)
                folders.append(
                    FolderEntry(
                        name=entry.name,
                        path=child,
                        mtime=datetime.fromtimestamp(st.st_mtime_ns / 1e9, tz=timezone.utc),
                        label=plan.label(child),
                        cover=self._cover(root_id, root_path, child, st.st_mtime_ns),
                    )
                )
        return FolderListing(root_id=root_id, path=rel, label=plan.label(rel), folders=folders, files=files, total_files=len(file_entries), next_cursor=next_cursor)

    def _cover(self, root_id: str, root_path: Path, rel: str, mtime_ns: int) -> list[CoverImage]:
        """Up to four newest images directly in a folder, cached by the folder's mtime."""
        key = (root_id, rel)
        hit = self._covers.get(key)
        if hit is not None and hit[0] == mtime_ns:
            return hit[1]
        cover: list[CoverImage] = []
        if self.index is not None:
            cover = self.index.newest_in_dir(root_id, rel, COVER_SIZE)
        if not cover:
            found: list[tuple[int, str]] = []
            try:
                with os.scandir(resolve_in_root(root_path, rel, follow_symlinks=self.follow_symlinks)) as it:
                    for i, entry in enumerate(it):
                        if i >= 2000:
                            break
                        if not is_ignored_name(entry.name) and self.kind_of(entry.name) == "image":
                            try:
                                found.append((entry.stat().st_mtime_ns, entry.name))
                            except OSError:
                                continue
            except (OSError, HanaikadaError):
                found = []
            found.sort(reverse=True)
            cover = [CoverImage(path=_join(rel, name), version=str(mtime)) for mtime, name in found[:COVER_SIZE]]
        if len(self._covers) > 5000:
            self._covers.clear()
        self._covers[key] = (mtime_ns, cover)
        return cover

    def cover(self, root_id: str, rel_path: str) -> list[CoverImage]:
        _, root_path, target, rel = self.resolve(root_id, rel_path, kind="dir")
        return self._cover(root_id, root_path, rel, target.stat().st_mtime_ns)

    def tree(self, root_id: str, rel_path: str = "", depth: int = 1) -> TreeNode:
        """A folder and its visible subfolders, ``depth`` levels down; deeper levels only say whether they exist."""
        root, root_path, target, rel = self.resolve(root_id, rel_path, kind="dir")
        plan = self.plan(root_id)

        def subdirs(path: Path, rel_dir: str) -> list[tuple[str, Path]]:
            out: list[tuple[str, Path]] = []
            try:
                with os.scandir(path) as it:
                    for entry in it:
                        if is_ignored_name(entry.name):
                            continue
                        try:
                            if not entry.is_dir(follow_symlinks=True):
                                continue
                        except OSError:
                            continue
                        child = _join(rel_dir, entry.name)
                        if plan.dir_visible(child) and self._link_allowed(root_path, Path(entry.path)):
                            out.append((child, Path(entry.path)))
            except OSError:
                return []
            return sorted(out, key=lambda item: item[0].lower())

        def build(path: Path, rel_dir: str, level: int) -> TreeNode:
            name = rel_dir.rsplit("/", 1)[-1] if rel_dir else root.name
            children = subdirs(path, rel_dir)
            node = TreeNode(name=name, path=rel_dir, label=plan.label(rel_dir), has_children=bool(children))
            if level < depth:
                node.children = [build(child_path, child_rel, level + 1) for child_rel, child_path in children]
            return node

        return build(target, rel, 0)

    def list_combined(self) -> CombinedListing:
        """The output folders of every root side by side, as folders only, for Browse's "All folders".

        A root that is itself its output folder (a custom root, or one pointed at ``output/``)
        is one entry named after the root; an install root lends its output folders, in the
        layout's order, so a WebUI shows ``txt2img-images``, ``extras-images`` and so on. Roots
        keep their configured order. A folder another entry already reaches (a root inside
        another root's output folder, or a link to it) is left out, and names that collide are
        told apart by their root's name. A missing or unreadable root is reported, not raised.
        """
        missing: list[str] = []
        # (root, root path, rel, real path, layout label, whether it is the root itself)
        found: list[tuple[ImageRoot, Path, str, Path, str | None, bool]] = []
        for root in self._roots():
            root_path = Path(root.path).expanduser().resolve()
            try:
                if not root_path.is_dir():
                    missing.append(root.id)
                    continue
                outputs = self.plan(root.id).outputs
            except OSError:
                missing.append(root.id)
                continue
            # An output folder inside another of the same root is reached through the outer one.
            for out in outputs:
                if any(other.rel != out.rel and (other.rel == "" or out.rel.startswith(other.rel + "/")) for other in outputs):
                    continue
                if out.rel == "":
                    found.append((root, root_path, "", root_path, out.label, True))
                    continue
                try:
                    folder = resolve_in_root(root_path, out.rel, follow_symlinks=self.follow_symlinks)
                    if folder.is_dir():
                        found.append((root, root_path, out.rel, folder.resolve(), out.label, False))
                except (OSError, HanaikadaError):
                    continue

        # Shallowest first, so a folder is kept where it is reached first and anything below it
        # (another root, or the same directory through a link) is dropped; then back in order.
        claimed: list[Path] = []
        kept: list[int] = []
        for i in sorted(range(len(found)), key=lambda i: len(found[i][3].parts)):
            real = found[i][3]
            if any(real == c or c in real.parents for c in claimed):
                continue
            claimed.append(real)
            kept.append(i)
        entries = [found[i] for i in sorted(kept)]

        # Two roots may share a name; the second becomes "name 2" wherever it has to be named.
        seen: Counter[str] = Counter()
        root_names: dict[str, str] = {}
        for root in self._roots():
            seen[root.name] += 1
            root_names[root.id] = root.name if seen[root.name] == 1 else f"{root.name} {seen[root.name]}"
        names = [root_names[root.id] if is_root else rel.rsplit("/", 1)[-1] for root, _, rel, _, _, is_root in entries]
        # Case-insensitive, as a Windows user would read two names.
        counts = Counter(name.casefold() for name in names)

        folders: list[CombinedFolder] = []
        for name, (root, root_path, rel, real, label, is_root) in zip(names, entries):
            try:
                mtime_ns = real.stat().st_mtime_ns
            except OSError:
                continue
            folders.append(
                CombinedFolder(
                    name=name,
                    path=rel,
                    mtime=datetime.fromtimestamp(mtime_ns / 1e9, tz=timezone.utc),
                    label=label,
                    cover=self._cover(root.id, root_path, rel, mtime_ns),
                    root_id=root.id,
                    root_name=root_names[root.id],
                    display_name=name if counts[name.casefold()] == 1 else f"{name} ({root_names[root.id]})",
                    is_root=is_root,
                )
            )
        return CombinedListing(folders=folders, missing_roots=missing)

    # -- files and thumbnails -----------------------------------------------

    def file_path(self, root_id: str, rel_path: str) -> Path:
        return self.resolve(root_id, rel_path, kind="file")[2]

    def thumbnail(self, root_id: str, rel_path: str, size: int) -> Thumbnail:
        root, _, target, rel = self.resolve(root_id, rel_path, kind="file")
        if self.kind_of(target.name) != "image":
            raise NotFoundError(f"Not an image: {rel_path}")
        seed = None
        if root.layout == "invokeai" and size <= 256 and self.settings.settings.thumbnails.prefer_platform_thumbnails:
            thumb = self._thumb_of(root_id, rel)
            seed = thumb[0] if thumb else None
        return self.thumbnails.get(target, size, seed=seed)

    def thumbnail_cache(self) -> ThumbnailCacheInfo:
        files, size = self.thumbnails.usage()
        return ThumbnailCacheInfo(files=files, bytes=size, max_bytes=self.settings.settings.thumbnails.cache_max_mb * 1024 * 1024, path=str(self.thumbnails.cache_dir))

    def clear_thumbnail_cache(self) -> ThumbnailCacheInfo:
        self.thumbnails.clear()
        return self.thumbnail_cache()

    # -- companions ---------------------------------------------------------

    def _group(self, root_id: str, rel: str, path: Path, together: set[Path] | None = None) -> list[tuple[Path, str]]:
        """A path plus the sidecars that travel with it, each with its path relative to the root."""
        if path.is_dir() or self.kind_of(path.name) != "image":
            return [(path, rel)]
        lib = self.settings.settings.library
        members = [(path, rel)]
        for sidecar in sidecars_of(path, lib.sidecar_extensions, sorted(self.image_extensions), together):
            members.append((sidecar, _join(_parent(rel), sidecar.name)))
        return members

    def _thumb_of(self, root_id: str, rel: str) -> tuple[Path, str] | None:
        """An InvokeAI image's own thumbnail, which lives in the output folder's ``thumbnails`` tree."""
        if self.root(root_id).layout != "invokeai":
            return None
        plan = self.plan(root_id)
        output = plan.output_of(_parent(rel))
        if output is None or output.rel not in plan.thumbnail_dirs:
            return None
        thumb_rel = invokeai_thumbnail(rel, output.rel, plan.thumbnail_dirs[output.rel])
        if thumb_rel is None:
            return None
        path = self.root_path(root_id).joinpath(*thumb_rel.split("/"))
        return (path, thumb_rel) if path.is_file() else None

    def _move_thumb(self, src_root: str, src_rel: str, dest_root: str, dest_rel: str) -> None:
        """Carry an InvokeAI thumbnail to the place its image's new path calls for, when there is one."""
        thumb = self._thumb_of(src_root, src_rel)
        if thumb is None or self.root(dest_root).layout != "invokeai":
            return
        plan = self.plan(dest_root)
        output = plan.output_of(_parent(dest_rel))
        if output is None or output.rel not in plan.thumbnail_dirs:
            return
        new_rel = invokeai_thumbnail(dest_rel, output.rel, plan.thumbnail_dirs[output.rel])
        if new_rel is None:
            return
        target = self.root_path(dest_root).joinpath(*new_rel.split("/"))
        if target.exists():
            return
        try:
            move_path(thumb[0], target)
        except (OSError, HanaikadaError) as e:
            logger.info("The thumbnail of %s stayed behind: %s", src_rel, e)

    def companions(self, root_id: str, rel: str) -> list[str]:
        _, _, target, rel = self.resolve(root_id, rel, kind="file")
        out = [member_rel for _, member_rel in self._group(root_id, rel, target)[1:]]
        thumb = self._thumb_of(root_id, rel)
        if thumb is not None:
            out.append(thumb[1])
        return out

    # -- index hooks --------------------------------------------------------

    def after_created(self, root_id: str, rels: list[str], index_now: bool = False) -> None:
        for directory in sorted({_parent(r) for r in rels}):
            self.notify_changed(root_id, directory)
        if self.index is not None:
            images = [r for r in rels if self.kind_of(r) == "image"]
            if index_now:
                for rel in images:
                    try:
                        self.index.index_file(root_id, rel)
                    except HanaikadaError as e:
                        logger.info("Could not index %s: %s", rel, e.message)
            else:
                self.index.queue_files(root_id, images)

    # -- operations ---------------------------------------------------------

    @staticmethod
    def _renamed(member: Path, old_stem: str, new_stem: str, dest_dir: Path) -> Path:
        name = member.name
        return dest_dir / (new_stem + name[len(old_stem) :] if name.startswith(old_stem) else name)

    def _plan_pairs(self, group: list[tuple[Path, str]], dest_dir: Path, on_conflict: str, new_stem: str | None = None, copy: bool = False) -> list[tuple[Path, Path]] | None:
        """Pair each member with its target, applying a numeric suffix on conflict if asked.

        Returns None when ``on_conflict`` is ``skip`` and a target exists. A copy into its own
        folder clashes with itself; a move or rename onto the same path is a no-op.
        """
        src = group[0][0]
        old_stem = src.stem if src.is_file() else src.name
        stem = new_stem or old_stem
        for attempt in range(10_000):
            candidate = stem if attempt == 0 else f"{stem}_{attempt}"
            pairs = [(member, self._renamed(member, old_stem, candidate, dest_dir)) for member, _rel in group]
            clashes = [d for s, d in pairs if (d.exists() or d.is_symlink()) and (copy or d != s)]
            if not clashes:
                return pairs
            if on_conflict == "skip":
                return None
            if on_conflict != "rename":
                raise ConflictError(f"Target exists: {clashes[0].name}", {"targets": [str(c) for c in clashes]})
        raise ConflictError("Could not find a free name")

    def transfer(self, req: TransferRequest, copy: bool = False) -> OperationResult:
        """Move or copy files and folders, each with its companions, into one folder."""
        _, dest_root, dest_dir, dest_rel = self.resolve(req.dest_root_id, req.dest_dir, must_exist=False, kind="dir")
        dest_dir.mkdir(parents=True, exist_ok=True)
        result = OperationResult()
        changed: set[tuple[str, str]] = {(req.dest_root_id, dest_rel)}
        moving = set()
        for item in req.items:
            try:
                moving.add(self.resolve(item.root_id, item.path)[2])
            except HanaikadaError:
                continue
        for item in req.items:
            try:
                _, src_root, src, src_rel = self.resolve(item.root_id, item.path)
                if src == src_root:
                    raise InvalidPathError("Cannot move or copy a root")
                if src.is_dir() and (dest_dir == src or src in dest_dir.parents):
                    raise InvalidPathError("Cannot put a folder inside itself")
                if not copy and src.parent == dest_dir:
                    continue
                group = self._group(item.root_id, src_rel, src, moving)
                pairs = self._plan_pairs(group, dest_dir, req.on_conflict, copy=copy)
                if pairs is None:
                    result.skipped.append(item)
                    continue
                stats = {s: s.stat() for s, _ in pairs if s.is_file()}
                for s, d in pairs:
                    (copy_path if copy else move_path)(s, d)
                new_rel = to_rel(dest_root, pairs[0][1])
                if not copy:
                    self._move_thumb(item.root_id, src_rel, req.dest_root_id, new_rel)
                result.paths.append(PathRef(root_id=req.dest_root_id, path=new_rel))
                if self.index is not None:
                    if copy:
                        self.index.on_copied(req.dest_root_id, new_rel, pairs[0][1].is_dir())
                    else:
                        self.index.on_moved(item.root_id, src_rel, req.dest_root_id, new_rel, pairs[0][1].is_dir())
                if not copy:
                    for s, st in stats.items():
                        self.thumbnails.forget(s, st)
                    changed.add((item.root_id, _parent(src_rel)))
            except HanaikadaError as e:
                if not req.continue_on_error:
                    raise
                result.errors.append(OperationError(root_id=item.root_id, path=item.path, code=e.code, message=e.message))
            except OSError as e:
                if not req.continue_on_error:
                    raise HanaikadaError(f"{item.path}: {e.strerror or e}") from e
                result.errors.append(OperationError(root_id=item.root_id, path=item.path, code="os_error", message=str(e.strerror or e)))
        for root_id, rel in changed:
            self.notify_changed(root_id, rel)
        return result

    def rename(self, req: RenameRequest) -> OperationResult:
        _, root_path, src, rel = self.resolve(req.root_id, req.path)
        if src == root_path:
            raise InvalidPathError("Cannot rename a root")
        new_name = validate_name(req.new_name.strip())
        group = self._group(req.root_id, rel, src)
        if src.is_file():
            new_stem, _, new_ext = new_name.rpartition(".")
            if not new_stem or ("." + new_ext).lower() not in self.image_extensions | {src.suffix.lower()}:
                # "best" or "best.v2": the extension is kept, so a stem with dots is not cut.
                new_stem, new_ext = new_name, src.suffix.lstrip(".")
            if self.kind_of(f"{new_stem}.{new_ext}") == "file" and not self.settings.settings.library.show_all_files:
                raise ValidationError("The new name must keep an image extension")
            if new_ext and ("." + new_ext).lower() != src.suffix.lower():
                # A new extension renames only the file itself; its companions keep their names.
                pairs = [(src, src.parent / new_name)]
            else:
                pairs = self._plan_pairs(group, src.parent, "error", new_stem=new_stem) or []
        else:
            target = src.parent / new_name
            if target.exists():
                raise ConflictError(f"Target exists: {new_name}")
            pairs = [(src, target)]
        stats = {s: s.stat() for s, _ in pairs if s.is_file()}
        new_path = src
        for s, d in pairs:
            if s == d:
                continue
            rename_no_overwrite(s, d)
            if s == src:
                new_path = d
        new_rel = to_rel(root_path, new_path)
        if new_path != src and new_path.is_file():
            self._move_thumb(req.root_id, rel, req.root_id, new_rel)
        if self.index is not None and new_path != src:
            self.index.on_moved(req.root_id, rel, req.root_id, new_rel, new_path.is_dir())
        for s, st in stats.items():
            self.thumbnails.forget(s, st)
        self.notify_changed(req.root_id, _parent(rel))
        return OperationResult(paths=[PathRef(root_id=req.root_id, path=new_rel)])

    def delete(self, req: DeleteRequest) -> OperationResult:
        to_trash = self.settings.settings.library.delete_to_trash and not req.permanent
        result = OperationResult()
        targets: list[tuple[str, Path, Path, str]] = []
        for item in req.items:
            _, root_path, src, rel = self.resolve(item.root_id, item.path)
            if src == root_path:
                raise InvalidPathError("Cannot delete a root")
            targets.append((item.root_id, root_path, src, rel))
        deleting = {t[2] for t in targets}
        for root_id, _root_path, src, rel in targets:
            if not src.exists():
                continue
            is_dir = src.is_dir()
            group = self._group(root_id, rel, src, deleting)
            thumb = self._thumb_of(root_id, rel) if not is_dir else None
            if thumb is not None:
                group.append(thumb)
            for member, _member_rel in group:
                st = member.stat() if member.is_file() else None
                if to_trash:
                    result.trashed_to.append(self._trash(member))
                else:
                    remove_path(member)
                if st is not None:
                    self.thumbnails.forget(member, st)
            if self.index is not None:
                self.index.on_deleted(root_id, rel, is_dir)
            result.paths.append(PathRef(root_id=root_id, path=rel))
            self.notify_changed(root_id, _parent(rel))
        return result

    def trash_location(self) -> str:
        """Where deleted files go: the system trash, or the fallback folder in the data directory."""
        if sys.platform == "win32":
            return "Recycle Bin"
        if sys.platform == "darwin":
            return "~/.Trash"
        xdg = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
        return f"{xdg}/Trash (fallback: {self.settings.data_dir / 'trash'})"

    def _trash(self, path: Path) -> str:
        try:
            from send2trash import send2trash

            send2trash(str(path))
            return "system"
        except Exception as e:  # noqa: BLE001 - any trash failure falls back to our own folder
            logger.info("System trash failed for %s (%s); using the data directory", path, e)
        fallback = self.settings.data_dir / "trash" / time.strftime("%Y%m%d-%H%M%S")
        fallback.mkdir(parents=True, exist_ok=True)
        move_path(path, unique_path(fallback / path.name))
        return str(fallback)

    def create_folder(self, req: FolderCreate) -> PathRef:
        _, root_path, parent, rel = self.resolve(req.root_id, req.path, kind="dir")
        name = validate_name(req.name.strip())
        new_rel = _join(rel, name)
        if not self.plan(req.root_id).dir_visible(new_rel):
            raise InvalidPathError("A folder here would be hidden by the root's layout")
        target = parent / name
        if target.exists():
            raise ConflictError(f"Already exists: {name}")
        target.mkdir()
        self.notify_changed(req.root_id, rel)
        return PathRef(root_id=req.root_id, path=to_rel(root_path, target))

    def open_upload(self, root_id: str, rel_dir: str, name: str, total: int | None = None, on_conflict: str = "error") -> UploadWriter:
        """Start a streamed upload. The name may contain ``/`` to keep a dropped folder's structure."""
        parts = [p for p in name.replace("\\", "/").split("/") if p]
        if not parts:
            raise InvalidPathError("Empty file name")
        for p in parts:
            validate_name(p)
        if self.kind_of(parts[-1]) == "file" and not self.settings.settings.library.show_all_files:
            raise ValidationError(f"Not an image: {parts[-1]}")
        folder = "/".join([p for p in [rel_dir.strip("/"), *parts[:-1]] if p])
        _, root_path, dest_dir, _ = self.resolve(root_id, folder, must_exist=False, kind="dir")
        target = dest_dir / parts[-1]
        if target.exists():
            if on_conflict != "rename":
                raise ConflictError(f"Target exists: {parts[-1]}", {"target": to_rel(root_path, target)})
            target = unique_path(target)
        dest_dir.mkdir(parents=True, exist_ok=True)
        return UploadWriter(self, root_id, target, total)

    def open_in_file_manager(self, req: OpenRequest) -> None:
        """Show a file in the system file manager, or open it with its default application.

        Works only when the browser and the server are the same machine; the interface hides it otherwise.
        """
        _, _, target, _ = self.resolve(req.root_id, req.path)
        if sys.platform == "win32":
            command = ["explorer", f"/select,{target}"] if req.reveal and target.is_file() else ["explorer", str(target)]
            if not req.reveal:
                os.startfile(str(target))  # type: ignore[attr-defined]
                return
        elif sys.platform == "darwin":
            command = ["open", "-R", str(target)] if req.reveal else ["open", str(target)]
        else:
            command = ["xdg-open", str(target.parent if req.reveal and target.is_file() else target)]
        try:
            subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        except OSError as e:
            raise HanaikadaError(f"Cannot open the file manager: {e}") from e

    def zip_stream(self, items: list[PathRef]) -> Iterator[bytes]:
        """A zip of the given files, produced while it is sent; folders are included whole."""
        members: list[tuple[Path, str]] = []
        used: set[str] = set()
        for item in items:
            target = self.resolve(item.root_id, item.path)[2]
            paths = [target] if target.is_file() else sorted(p for p in target.rglob("*") if p.is_file() and not is_ignored_name(p.name))
            for path in paths:
                arcname = path.name if target.is_file() else f"{target.name}/{path.relative_to(target).as_posix()}"
                base, dot, ext = arcname.rpartition(".")
                counter = 1
                while arcname in used:
                    arcname = f"{base}_{counter}{dot}{ext}" if dot else f"{arcname}_{counter}"
                    counter += 1
                used.add(arcname)
                members.append((path, arcname))
        if not members:
            raise ValidationError("Nothing to download")

        def generate() -> Iterator[bytes]:
            sink = _ZipStream()
            with zipfile.ZipFile(sink, "w", compression=zipfile.ZIP_STORED, allowZip64=True) as archive:
                for path, arcname in members:
                    with open(path, "rb") as src, archive.open(zipfile.ZipInfo.from_file(path, arcname), "w") as dst:
                        while True:
                            block = src.read(1024 * 1024)
                            if not block:
                                break
                            dst.write(block)
                            data = sink.drain()
                            if data:
                                yield data
                    data = sink.drain()
                    if data:
                        yield data
            data = sink.drain()
            if data:
                yield data

        return generate()
