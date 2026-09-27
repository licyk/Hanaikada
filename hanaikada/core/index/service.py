"""The index: image rows, tags and search, and the scanner that fills them."""

import json
import logging
import random
import sqlite3
import threading
from collections.abc import Iterable
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

from hanaikada.core.db import Database
from hanaikada.core.errors import ConflictError, HanaikadaError, IndexBusyError, NotFoundError, UnsupportedFileError, ValidationError
from hanaikada.core.events import EventBus
from hanaikada.core.events.models import IndexChangedEvent, TagsChangedEvent
from hanaikada.core.index import records
from hanaikada.core.index.models import (
    TAG_TYPES,
    DayCount,
    Facets,
    FacetValue,
    ImageDetail,
    ImageRecord,
    Neighbours,
    RootIndexSummary,
    ScanRequest,
    ScanStatus,
    SearchPage,
    SearchQuery,
    Stats,
    Tag,
    TagCreate,
    TagImagesRequest,
    TagOperationResult,
    TagUpdate,
    TextField,
)
from hanaikada.core.index.records import LISTING_COLUMNS, TagCache, now_iso
from hanaikada.core.index.scanner import PRIORITY_FILES, PRIORITY_FOLDER, PRIORITY_REPARSE, PRIORITY_ROOT, Job, Scanner
from hanaikada.core.index.search import REGEX_BATCH, REGEX_SCAN_CAP, build_where, compile_regex, encode_cursor, order_and_keyset
from hanaikada.core.index.tags import derive_tags
from hanaikada.core.library.layouts import LayoutPlan
from hanaikada.core.library.models import CoverImage
from hanaikada.core.library.thumbnails import ThumbnailService
from hanaikada.core.metadata import MetadataService
from hanaikada.core.metadata.models import GenerationInfo, ParsedImage, RawMetadata
from hanaikada.core.metadata.views import RawView, raw_view
from hanaikada.core.settings import SettingsService

if TYPE_CHECKING:
    from hanaikada.core.library import LibraryService

logger = logging.getLogger(__name__)

MISSING_GRACE = timedelta(days=7)
EVENT_PATH_CAP = 200
TAGS_BACKUP_FILE = "tags-backup.json"
RESTORE_KEY = "hanaikada.tags_restore_pending"


def _parent(rel: str) -> str:
    return rel.rsplit("/", 1)[0] if "/" in rel else ""


def _like_prefix(rel: str) -> str:
    return rel.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "/%"


class IndexService:
    def __init__(self, settings: SettingsService, db: Database, events: EventBus, library: "LibraryService", metadata: MetadataService, thumbnails: ThumbnailService) -> None:
        self.settings = settings
        self.db = db
        self.events = events
        self.library = library
        self.metadata = metadata
        self.thumbnails = thumbnails
        self.tags = TagCache()
        self.scanner = Scanner(self)
        self._write_lock = threading.Lock()
        library.index = self
        backup = settings.data_dir / TAGS_BACKUP_FILE
        if db.created and backup.is_file():
            db.set_client_state(RESTORE_KEY, True)

    # -- lifecycle -------------------------------------------------------------------------------

    def start(self, scan_on_start: bool | None = None) -> None:
        """Start the scanner thread and, when ``index.scan_on_start``, queue every enabled root."""
        self.scanner.start()
        if self.settings.settings.index.scan_on_start if scan_on_start is None else scan_on_start:
            for root in self.library.list_roots():
                if root.enabled and root.index and root.exists:
                    self.queue_root(root.id, full=False)

    def close(self) -> None:
        self.scanner.stop()

    # -- queueing --------------------------------------------------------------------------------

    def queue_root(self, root_id: str, full: bool = False) -> bool:
        """Queue a background scan of a root; without a running scanner (the command line) there is none."""
        if not self.scanner.running:
            return False
        return self.scanner.submit(Job("root", root_id, full=full), PRIORITY_ROOT)

    def queue_files(self, root_id: str, rels: list[str]) -> None:
        if rels and self.scanner.running and self._root_indexed(root_id):
            self.scanner.submit(Job("files", root_id, rels=list(rels)), PRIORITY_FILES)

    def _root_indexed(self, root_id: str) -> bool:
        try:
            root = self.library.root(root_id)
        except NotFoundError:
            return False
        return root.enabled and root.index

    def request_scan(self, req: ScanRequest) -> ScanStatus:
        """Queue a scan: one folder, one root, or every root. A full rebuild of a root already rebuilding is refused."""
        if req.reparse:
            if req.root_id is not None:
                self.library.root(req.root_id)
            self.scanner.submit(Job("reparse", req.root_id), PRIORITY_REPARSE)
            return self.status()
        roots = [self.library.get_root(req.root_id)] if req.root_id else [r for r in self.library.list_roots() if r.enabled and r.index]
        for root in roots:
            if req.full and self.scanner.is_busy_with_full(root.id):
                raise IndexBusyError(f"A full rebuild of {root.name} is already running")
        for root in roots:
            if req.path:
                self.library.resolve(root.id, req.path, kind="dir")
                self.scanner.submit(Job("folder", root.id, rel=req.path.strip("/"), full=req.full), PRIORITY_FOLDER)
            else:
                self.scanner.submit(Job("root", root.id, full=req.full), PRIORITY_ROOT)
        return self.status()

    def cancel(self) -> ScanStatus:
        self.scanner.cancel()
        return self.status()

    def status(self) -> ScanStatus:
        roots = []
        for root in self.library.list_roots():
            state = self.scanner.states.get(root.id)
            roots.append(state.model_copy() if state else self._idle_state(root.id))
        current = self.scanner.current
        return ScanStatus(running=current is not None and current.kind != "watch", queued=self.scanner.pending(), roots=roots)

    @staticmethod
    def _idle_state(root_id: str):  # type: ignore[no-untyped-def]
        from hanaikada.core.index.models import RootScanState

        return RootScanState(root_id=root_id)

    def wait_idle(self, timeout: float | None = None) -> bool:
        return self.scanner.wait_idle(timeout)

    def scan_now(self, req: ScanRequest) -> None:
        """Run a scan in the calling thread, for the command line. Progress goes out as events."""
        if req.reparse:
            self.reparse(req.root_id)
            return
        roots = [self.library.get_root(req.root_id)] if req.root_id else [r for r in self.library.list_roots() if r.enabled and r.index]
        for root in roots:
            if req.path:
                self.library.resolve(root.id, req.path, kind="dir")
                from hanaikada.core.index.scanner import _Counts

                self.scanner.scan_tree(root.id, req.path.strip("/"), req.full, True, _Counts(), publish=True)
            else:
                self.scanner.scan_root(root.id, req.full)

    # -- reading files ---------------------------------------------------------------------------

    def _read(self, path: Path, siblings: set[str] | None) -> ParsedImage:
        return self.metadata.read(path, siblings)

    def _write_parsed(self, conn: sqlite3.Connection, root_id: str, rel: str, st: Any, parsed: ParsedImage) -> tuple[int, bool]:
        from hanaikada.core.library.service import _ctime_ns

        values = records.image_values(root_id, rel, st.st_size, st.st_mtime_ns, _ctime_ns(st), parsed)
        image_id, created = records.upsert_image(conn, values)
        records.replace_text(conn, image_id, parsed, self.settings.settings.index.max_raw_bytes)
        records.set_auto_tags(conn, self.tags, image_id, derive_tags(parsed.info, parsed.raw.width, parsed.raw.height))
        return image_id, created

    def index_batch(self, root_id: str, rel_dir: str, items: list[tuple[str, Path, Any]], siblings: set[str] | None = None) -> tuple[int, int]:
        """Read and write a batch of files of one folder in one transaction. Returns ``(indexed, failed)``."""
        parsed: list[tuple[str, Any, ParsedImage]] = []
        failed = 0
        for name, path, st in items:
            rel = f"{rel_dir}/{name}" if rel_dir else name
            try:
                result = self._read(path, siblings)
            except UnsupportedFileError as e:
                # Kept as a row with the error, so the file is not read again at every scan.
                result = ParsedImage(info=GenerationInfo(), raw=RawMetadata(), error=e.message)
            except OSError as e:
                logger.debug("Cannot read %s: %s", path, e)
                failed += 1
                continue
            except Exception as e:  # noqa: BLE001 - one bad file never stops a scan
                logger.warning("Reading %s failed: %s", path, e)
                result = ParsedImage(info=GenerationInfo(), raw=RawMetadata(), error=f"{type(e).__name__}: {e}")
            if result.error:
                failed += 1
            parsed.append((rel, st, result))
        added: list[str] = []
        updated: list[str] = []
        with self._write_lock, self.db.transaction() as conn:
            for rel, st, result in parsed:
                _, created = self._write_parsed(conn, root_id, rel, st, result)
                (added if created else updated).append(rel)
        self._changed(root_id, rel_dir, added=added, updated=updated)
        return sum(1 for _, _, result in parsed if not result.error), failed

    def index_files(self, root_id: str, rels: list[str]) -> int:
        """Index the given files now, grouped by folder. Files that vanished are marked missing."""
        by_dir: dict[str, list[str]] = {}
        for rel in rels:
            by_dir.setdefault(_parent(rel), []).append(rel)
        done = 0
        for rel_dir, group in by_dir.items():
            items = []
            gone = []
            for rel in group:
                try:
                    _, _, path, rel = self.library.resolve(root_id, rel, kind="file")
                    items.append((rel.rsplit("/", 1)[-1], path, path.stat()))
                except (HanaikadaError, OSError):
                    gone.append(rel)
            if gone:
                self.mark_missing(root_id, gone)
            for start in range(0, len(items), 50):
                ok, _ = self.index_batch(root_id, rel_dir, items[start : start + 50])
                done += ok
        return done

    def index_file(self, root_id: str, rel: str) -> ImageRecord:
        """Index one file now, whatever the root's settings, and return its row."""
        _, _, path, rel = self.library.resolve(root_id, rel, kind="file")
        if self.library.kind_of(path.name) != "image":
            raise UnsupportedFileError(f"Not an image: {rel}")
        self.index_batch(root_id, _parent(rel), [(path.name, path, path.stat())])
        record = self.record_by_path(root_id, rel)
        if record is None:
            raise NotFoundError(f"Could not index {rel}")
        return record

    # -- folders and rows the scanner uses --------------------------------------------------------

    def folder_mtime(self, root_id: str, rel: str) -> int | None:
        row = self.db.fetchone("SELECT mtime_ns FROM folders WHERE root_id = ? AND rel_path = ?", (root_id, rel))
        return None if row is None else int(row["mtime_ns"])

    def known_subfolders(self, root_id: str, rel: str) -> list[str]:
        return [r["rel_path"] for r in self.db.fetchall("SELECT rel_path FROM folders WHERE root_id = ? AND parent = ?", (root_id, rel))]

    def folders_of(self, root_id: str) -> list[tuple[str, int]]:
        return [(r["rel_path"], int(r["mtime_ns"])) for r in self.db.fetchall("SELECT rel_path, mtime_ns FROM folders WHERE root_id = ?", (root_id,))]

    def set_folder(self, root_id: str, rel: str, mtime_ns: int, subdirs: list[str]) -> None:
        """Record a folder as scanned, and forget child folders that no longer exist."""
        with self._write_lock, self.db.transaction() as conn:
            records.upsert_folder(conn, root_id, rel, mtime_ns)
            known = {r["rel_path"] for r in conn.execute("SELECT rel_path FROM folders WHERE root_id = ? AND parent = ?", (root_id, rel))}
        for gone in known - set(subdirs):
            self.forget_folder(root_id, gone)

    def forget_folder(self, root_id: str, rel: str) -> None:
        """A folder vanished: drop its folder rows and mark its images missing."""
        stamp = now_iso()
        with self._write_lock, self.db.transaction() as conn:
            conn.execute("DELETE FROM folders WHERE root_id = ? AND (rel_path = ? OR rel_path LIKE ? ESCAPE '\\')", (root_id, rel, _like_prefix(rel)))
            if rel:
                cursor = conn.execute(
                    "UPDATE images SET missing_since = ? WHERE root_id = ? AND missing_since IS NULL AND (dir = ? OR dir LIKE ? ESCAPE '\\')",
                    (stamp, root_id, rel, _like_prefix(rel)),
                )
                changed = cursor.rowcount
            else:
                changed = 0
        if changed:
            self._changed(root_id, rel, removed=[rel], more=True)

    def stale_files(self, root_id: str, rel_dir: str, files: dict[str, tuple[int, int]], full: bool) -> list[str]:
        """The files of a folder whose row is absent, older, missing or failed to parse before."""
        if full:
            return sorted(files)
        rows = {
            r["name"]: (r["size"], r["mtime_ns"], r["missing_since"])
            for r in self.db.fetchall("SELECT name, size, mtime_ns, missing_since FROM images WHERE root_id = ? AND dir = ?", (root_id, rel_dir))
        }
        out = []
        for name, (size, mtime) in files.items():
            row = rows.get(name)
            if row is None or row[0] != size or row[1] != mtime or row[2] is not None:
                out.append(name)
        return sorted(out)

    def missing_in_dir(self, root_id: str, rel_dir: str, present: set[str]) -> None:
        rows = self.db.fetchall("SELECT name FROM images WHERE root_id = ? AND dir = ? AND missing_since IS NULL", (root_id, rel_dir))
        gone = [f"{rel_dir}/{r['name']}" if rel_dir else r["name"] for r in rows if r["name"] not in present]
        if gone:
            self.mark_missing(root_id, gone)

    def mark_missing(self, root_id: str, rels: list[str]) -> None:
        stamp = now_iso()
        with self._write_lock, self.db.transaction() as conn:
            conn.executemany("UPDATE images SET missing_since = ? WHERE root_id = ? AND rel_path = ? AND missing_since IS NULL", [(stamp, root_id, rel) for rel in rels])
        by_dir: dict[str, list[str]] = {}
        for rel in rels:
            by_dir.setdefault(_parent(rel), []).append(rel)
        for rel_dir, group in by_dir.items():
            self._changed(root_id, rel_dir, removed=group)

    def reconcile(self, root_id: str) -> int:
        """Delete rows missing for longer than the grace period. Returns how many are still missing."""
        cutoff = (datetime.now(timezone.utc) - MISSING_GRACE).isoformat(timespec="seconds")
        with self._write_lock, self.db.transaction() as conn:
            conn.execute("DELETE FROM images WHERE root_id = ? AND missing_since IS NOT NULL AND missing_since < ?", (root_id, cutoff))
            records.delete_empty_auto_tags(conn)
        self.tags.clear()
        row = self.db.fetchone("SELECT COUNT(*) AS n FROM images WHERE root_id = ? AND missing_since IS NOT NULL", (root_id,))
        return int(row["n"]) if row else 0

    def after_root_scan(self, root_id: str, plan: LayoutPlan) -> None:
        if plan.invokeai_db is not None and self.settings.settings.index.invokeai_read_db:
            try:
                self.import_invokeai_boards(root_id, plan)
            except (sqlite3.Error, OSError) as e:
                logger.warning("Could not read the InvokeAI database %s: %s", plan.invokeai_db, e)
        if self.db.get_client_state(RESTORE_KEY):
            self.restore_custom_tags()

    def pregenerate_thumbnails(self, root_id: str, rels: list[str], cancel: threading.Event | None = None) -> None:
        for rel in rels:
            if cancel is not None and cancel.is_set():
                return
            try:
                self.library.thumbnail(root_id, rel, 256)
            except (HanaikadaError, OSError, ValueError) as e:
                logger.debug("No thumbnail for %s: %s", rel, e)
            except Exception as e:  # noqa: BLE001 - Pillow raises many types on broken images
                logger.debug("No thumbnail for %s: %s", rel, e)

    # -- listing support -------------------------------------------------------------------------

    def _blur_tag_ids(self) -> set[int]:
        names = self.settings.settings.content.blur_tags
        if not names:
            return set()
        rows = self.db.fetchall(f"SELECT id FROM tags WHERE name IN ({', '.join('?' for _ in names)})", names)
        return {r["id"] for r in rows}

    def _records(self, rows: list[sqlite3.Row]) -> list[ImageRecord]:
        ids = [r["id"] for r in rows]
        with self.db._lock:
            manual = records.manual_tag_ids(self.db._conn, ids)
            blur_ids = self._blur_tag_ids()
            blurred = records.images_with_tags(self.db._conn, ids, blur_ids) if blur_ids else set()
        return [records.record_from_row(r, manual.get(r["id"], []), r["id"] in blurred) for r in rows]

    def rows_for_dir(self, root_id: str, rel_dir: str) -> dict[str, ImageRecord]:
        rows = self.db.fetchall(f"SELECT {LISTING_COLUMNS} FROM images WHERE root_id = ? AND dir = ?", (root_id, rel_dir))
        return {record.name: record for record in self._records(rows)}

    def newest_in_dir(self, root_id: str, rel_dir: str, count: int) -> list[CoverImage]:
        rows = self.db.fetchall(
            "SELECT rel_path, mtime_ns FROM images WHERE root_id = ? AND dir = ? AND missing_since IS NULL ORDER BY mtime_ns DESC LIMIT ?",
            (root_id, rel_dir, count),
        )
        return [CoverImage(path=r["rel_path"], version=str(r["mtime_ns"])) for r in rows]

    def record_by_path(self, root_id: str, rel: str) -> ImageRecord | None:
        row = self.db.fetchone(f"SELECT {LISTING_COLUMNS} FROM images WHERE root_id = ? AND rel_path = ?", (root_id, rel))
        return self._records([row])[0] if row else None

    # -- changes made by the application ---------------------------------------------------------

    def _changed(self, root_id: str, rel_dir: str, added: list[str] | None = None, updated: list[str] | None = None, removed: list[str] | None = None, more: bool = False) -> None:
        added, updated, removed = added or [], updated or [], removed or []
        if not (added or updated or removed or more):
            return
        more = more or max(len(added), len(updated), len(removed)) > EVENT_PATH_CAP
        self.events.publish(
            IndexChangedEvent(root_id=root_id, rel_dir=rel_dir, added=added[:EVENT_PATH_CAP], updated=updated[:EVENT_PATH_CAP], removed=removed[:EVENT_PATH_CAP], more=more)
        )

    def on_moved(self, src_root: str, src_rel: str, dst_root: str, dst_rel: str, is_dir: bool) -> None:
        """Rewrite the rows of a moved file or folder, keeping their tags."""
        with self._write_lock, self.db.transaction() as conn:
            if is_dir:
                rows = conn.execute("SELECT id, rel_path FROM images WHERE root_id = ? AND rel_path LIKE ? ESCAPE '\\'", (src_root, _like_prefix(src_rel))).fetchall()
                conn.execute("DELETE FROM folders WHERE root_id = ? AND (rel_path = ? OR rel_path LIKE ? ESCAPE '\\')", (src_root, src_rel, _like_prefix(src_rel)))
                moves = [(r["id"], dst_rel + r["rel_path"][len(src_rel) :]) for r in rows]
            else:
                row = conn.execute("SELECT id FROM images WHERE root_id = ? AND rel_path = ?", (src_root, src_rel)).fetchone()
                moves = [(row["id"], dst_rel)] if row else []
            for image_id, new_rel in moves:
                conn.execute("DELETE FROM images WHERE root_id = ? AND rel_path = ? AND id != ?", (dst_root, new_rel, image_id))
                name = new_rel.rsplit("/", 1)[-1]
                ext = ("." + name.rsplit(".", 1)[1].lower()) if "." in name else ""
                conn.execute("UPDATE images SET root_id = ?, rel_path = ?, dir = ?, name = ?, ext = ? WHERE id = ?", (dst_root, new_rel, _parent(new_rel), name, ext, image_id))
        self._changed(src_root, _parent(src_rel), removed=[src_rel])
        self._changed(dst_root, _parent(dst_rel), added=[dst_rel])
        if is_dir:
            if self._root_indexed(dst_root) and self.scanner.running:
                self.scanner.submit(Job("folder", dst_root, rel=dst_rel), PRIORITY_FOLDER)
        elif not moves:
            self.queue_files(dst_root, [dst_rel])
        self.backup_custom_tags()

    def on_copied(self, root_id: str, rel: str, is_dir: bool) -> None:
        if is_dir:
            if self._root_indexed(root_id) and self.scanner.running:
                self.scanner.submit(Job("folder", root_id, rel=rel), PRIORITY_FOLDER)
        else:
            self.queue_files(root_id, [rel])

    def on_deleted(self, root_id: str, rel: str, is_dir: bool) -> None:
        with self._write_lock, self.db.transaction() as conn:
            if is_dir:
                conn.execute("DELETE FROM images WHERE root_id = ? AND rel_path LIKE ? ESCAPE '\\'", (root_id, _like_prefix(rel)))
                conn.execute("DELETE FROM folders WHERE root_id = ? AND (rel_path = ? OR rel_path LIKE ? ESCAPE '\\')", (root_id, rel, _like_prefix(rel)))
            else:
                conn.execute("DELETE FROM images WHERE root_id = ? AND rel_path = ?", (root_id, rel))
        self._changed(root_id, _parent(rel), removed=[rel], more=is_dir)
        self.backup_custom_tags()

    def forget_root(self, root_id: str) -> None:
        with self._write_lock, self.db.transaction() as conn:
            conn.execute("DELETE FROM images WHERE root_id = ?", (root_id,))
            conn.execute("DELETE FROM folders WHERE root_id = ?", (root_id,))
            records.delete_empty_auto_tags(conn)
        self.tags.clear()
        self.scanner.states.pop(root_id, None)

    # -- one image ---------------------------------------------------------------------------------

    def _row(self, image_id: int) -> sqlite3.Row:
        row = self.db.fetchone("SELECT *, parse_error IS NOT NULL AS has_error FROM images WHERE id = ?", (image_id,))
        if row is None:
            raise NotFoundError(f"No image with id {image_id}")
        return row

    def detail(self, image_id: int) -> ImageDetail:
        row = self._row(image_id)
        record = self._records([row])[0]
        try:
            info = GenerationInfo.model_validate(records.info_json(row))
        except Exception:  # noqa: BLE001 - an older row the model no longer accepts is re-parsed later
            info = GenerationInfo()
        tags = [
            records.tag_from_row(t)
            for t in self.db.fetchall("SELECT t.* FROM tags t JOIN image_tags it ON it.tag_id = t.id WHERE it.image_id = ? ORDER BY t.type, t.name", (image_id,))
        ]
        chunks = [r["key"] for r in self.db.fetchall("SELECT key FROM image_text WHERE image_id = ? ORDER BY key", (image_id,))]
        companions: list[str] = []
        try:
            companions = self.library.companions(row["root_id"], row["rel_path"])
        except HanaikadaError:
            pass
        neighbours = Neighbours()
        before = self.db.fetchone(
            "SELECT id FROM images WHERE root_id = ? AND dir = ? AND missing_since IS NULL AND (mtime_ns > ? OR (mtime_ns = ? AND id > ?)) ORDER BY mtime_ns ASC, id ASC LIMIT 1",
            (row["root_id"], row["dir"], row["mtime_ns"], row["mtime_ns"], image_id),
        )
        after = self.db.fetchone(
            "SELECT id FROM images WHERE root_id = ? AND dir = ? AND missing_since IS NULL AND (mtime_ns < ? OR (mtime_ns = ? AND id < ?)) ORDER BY mtime_ns DESC, id DESC LIMIT 1",
            (row["root_id"], row["dir"], row["mtime_ns"], row["mtime_ns"], image_id),
        )
        neighbours.previous = before["id"] if before else None
        neighbours.next = after["id"] if after else None
        return ImageDetail(record=record, info=info, prompt=row["prompt"], parse_error=row["parse_error"], tags=tags, companions=companions, chunks=chunks, neighbours=neighbours)

    def by_path(self, root_id: str, rel: str) -> ImageDetail:
        """The detail of the image at a path, indexing it first when the index is behind."""
        _, _, path, rel = self.library.resolve(root_id, rel, kind="file")
        st = path.stat()
        row = self.db.fetchone("SELECT id, size, mtime_ns, missing_since FROM images WHERE root_id = ? AND rel_path = ?", (root_id, rel))
        if row is None or row["size"] != st.st_size or row["mtime_ns"] != st.st_mtime_ns or row["missing_since"] is not None:
            record = self.index_file(root_id, rel)
            return self.detail(record.id)
        return self.detail(row["id"])

    def _stored_raw(self, row: sqlite3.Row) -> tuple[RawMetadata, bool]:
        raw = RawMetadata(format=row["format"], width=row["width"], height=row["height"])
        truncated = False
        for chunk in self.db.fetchall("SELECT key, value, source, truncated FROM image_text WHERE image_id = ?", (row["id"],)):
            raw.chunks[chunk["key"]] = chunk["value"]
            if chunk["source"]:
                raw.chunk_sources[chunk["key"]] = chunk["source"]
            truncated = truncated or bool(chunk["truncated"])
        return raw, truncated

    def raw(self, image_id: int) -> RawView:
        """Every chunk whole, and the EXIF and container entries: read from the file when it is there."""
        row = self._row(image_id)
        raw: RawMetadata | None = None
        try:
            path = self.library.file_path(row["root_id"], row["rel_path"])
            raw = self.metadata.read_raw(path)
        except (HanaikadaError, OSError):
            raw = None
        stored_truncated: set[str] = set()
        if raw is None:
            raw, _ = self._stored_raw(row)
            stored_truncated = {r["key"] for r in self.db.fetchall("SELECT key FROM image_text WHERE image_id = ? AND truncated = 1", (image_id,))}
        return raw_view(raw, stored_truncated)

    def chunk(self, image_id: int, key: str) -> tuple[str, str]:
        """One chunk whole, and a file name to download it as: ``workflow.json``, ``parameters.txt``."""
        row = self._row(image_id)
        view = self.raw(image_id)
        for chunk in view.chunks:
            if chunk.key == key:
                value = chunk.value
                is_json = value.lstrip().startswith(("{", "["))
                stem = row["name"].rsplit(".", 1)[0]
                safe_key = "".join(c if c.isalnum() or c in "-_" else "_" for c in key)
                return value, f"{stem}.{safe_key}.{'json' if is_json else 'txt'}"
        raise NotFoundError(f"The image has no {key!r} chunk")

    def similar(self, image_id: int, by: str, limit: int = 200) -> SearchPage:
        row = self._row(image_id)
        q = SearchQuery(limit=limit)
        if by == "seed":
            if row["seed"] is None:
                return SearchPage(items=[])
            q.seed = records.seed_from_db(row["seed"])
        elif by == "model":
            if row["model_name"] is None:
                return SearchPage(items=[])
            q.models = [row["model_name"]]
        elif by == "prompt":
            prompt = (row["prompt"] or "").strip()
            if not prompt:
                return SearchPage(items=[])
            fields: list[TextField] = ["prompt"]
            q.text, q.text_in = prompt[:200], fields
        else:
            raise ValidationError("by must be seed, model or prompt")
        return self.search(q)

    # -- search ------------------------------------------------------------------------------------

    def search(self, q: SearchQuery) -> SearchPage:
        if q.sort == "random" and q.random_seed is None:
            q = q.model_copy(update={"random_seed": random.randint(1, 2**31 - 1)})
        clauses, params = build_where(q, self.db.fts)
        key, order, keyset = order_and_keyset(q, params)
        where = " AND ".join(clauses) if clauses else "1"
        paged_where = f"{where} AND {keyset}" if keyset else where
        regex = compile_regex(q.regex) if q.regex else None
        extra = ", prompt AS full_prompt, negative_prompt, model_name AS full_model, loras" if regex else ""
        sql = f"SELECT {LISTING_COLUMNS}, {key} AS sort_key{extra} FROM images WHERE {{where}} ORDER BY {order} LIMIT :limit"
        items: list[sqlite3.Row] = []
        last: sqlite3.Row | None = None
        exhausted = False
        if regex is None:
            params["limit"] = q.limit + 1
            rows = self.db.fetchall(sql.format(where=paged_where), params)
            exhausted = len(rows) <= q.limit
            items = rows[: q.limit]
            last = items[-1] if items else None
        else:
            fields = q.text_in or ["prompt", "negative", "name", "model", "loras"]
            scanned = 0
            batch_where = paged_where
            op = "<" if q.descending else ">"
            while True:
                params["limit"] = REGEX_BATCH
                rows = self.db.fetchall(sql.format(where=batch_where), params)
                filled = False
                for r in rows:
                    last = r
                    scanned += 1
                    haystacks = {"prompt": r["full_prompt"], "negative": r["negative_prompt"], "name": r["name"], "model": r["full_model"], "loras": r["loras"]}
                    if any(regex.search(haystacks[f] or "") for f in fields):
                        items.append(r)
                        if len(items) >= q.limit:
                            filled = True
                            break
                if filled or scanned >= REGEX_SCAN_CAP:
                    break  # more may follow: the cursor continues from the last row read
                if len(rows) < REGEX_BATCH or last is None:
                    exhausted = True
                    break
                params["cursor_value"], params["cursor_id"] = last["sort_key"], last["id"]
                batch_where = f"{where} AND ({key} {op} :cursor_value OR ({key} = :cursor_value AND id {op} :cursor_id))"
        next_cursor = None if exhausted or last is None else encode_cursor(q.sort, q.descending, last["sort_key"], last["id"])
        total = None
        if q.cursor is None and regex is None:
            count_params = {k: v for k, v in params.items() if k not in ("limit", "cursor_value", "cursor_id")}
            total = self._count(where, count_params)
        return SearchPage(items=self._records(items), next_cursor=next_cursor, total=total, random_seed=q.random_seed)

    def _count(self, where: str, params: dict[str, Any] | list[Any]) -> int:
        row = self.db.fetchone(f"SELECT COUNT(*) AS n FROM images WHERE {where}", params)
        return int(row["n"]) if row is not None else 0

    def random(self, limit: int = 128) -> SearchPage:
        return self.search(SearchQuery(sort="random", limit=limit))

    def facets(self, q: SearchQuery, limit: int = 50) -> Facets:
        clauses, params = build_where(q.model_copy(update={"cursor": None}), self.db.fts)
        where = " AND ".join(clauses) if clauses else "1"

        def top(expression: str) -> list[FacetValue]:
            rows = self.db.fetchall(
                f"SELECT {expression} AS value, COUNT(*) AS n FROM images WHERE {where} AND {expression} IS NOT NULL GROUP BY value ORDER BY n DESC, value LIMIT {int(limit)}",
                params,
            )
            return [FacetValue(value=str(r["value"]), count=r["n"]) for r in rows]

        total = self._count(where, params)
        return Facets(
            platforms=top("platform"),
            models=top("model_name"),
            samplers=top("sampler_norm"),
            sizes=top("CASE WHEN width IS NULL THEN NULL ELSE width || 'x' || height END"),
            total=total,
        )

    def stats(self, root_ids: list[str] | None = None) -> Stats:
        where = "missing_since IS NULL"
        params: list[Any] = []
        if root_ids:
            where += f" AND root_id IN ({', '.join('?' for _ in root_ids)})"
            params.extend(root_ids)
        day = "date(mtime_ns / 1000000000, 'unixepoch', 'localtime')"
        per_day = [DayCount(day=r["d"], count=r["n"]) for r in self.db.fetchall(f"SELECT {day} AS d, COUNT(*) AS n FROM images WHERE {where} GROUP BY d ORDER BY d", params)]
        per_month = [
            DayCount(day=r["d"], count=r["n"]) for r in self.db.fetchall(f"SELECT substr({day}, 1, 7) AS d, COUNT(*) AS n FROM images WHERE {where} GROUP BY d ORDER BY d", params)
        ]

        def top(column: str) -> list[FacetValue]:
            rows = self.db.fetchall(f"SELECT {column} AS value, COUNT(*) AS n FROM images WHERE {where} AND {column} IS NOT NULL GROUP BY value ORDER BY n DESC LIMIT 20", params)
            return [FacetValue(value=str(r["value"]), count=r["n"]) for r in rows]

        lora_rows = self.db.fetchall(
            f"SELECT t.name AS value, COUNT(*) AS n FROM image_tags it JOIN tags t ON t.id = it.tag_id JOIN images i ON i.id = it.image_id "
            f"WHERE t.type = 'lora' AND {where.replace('missing_since', 'i.missing_since').replace('root_id', 'i.root_id')} GROUP BY t.name ORDER BY n DESC LIMIT 20",
            params,
        )
        total = self._count(where, params)
        return Stats(
            total=total,
            per_day=per_day,
            per_month=per_month,
            platforms=top("platform"),
            models=top("model_name"),
            samplers=top("sampler_norm"),
            loras=[FacetValue(value=r["value"], count=r["n"]) for r in lora_rows],
        )

    def roots_summary(self) -> list[RootIndexSummary]:
        out = []
        for root in self.library.list_roots():
            row = self.db.fetchone(
                "SELECT COUNT(*) AS n, SUM(missing_since IS NOT NULL) AS missing, SUM(parse_error IS NOT NULL AND platform != 'none') AS failed FROM images WHERE root_id = ?",
                (root.id,),
            )
            state = self.scanner.states.get(root.id)
            out.append(
                RootIndexSummary(
                    root_id=root.id,
                    images=int(row["n"] or 0) if row else 0,
                    missing=int(row["missing"] or 0) if row else 0,
                    failed=int(row["failed"] or 0) if row else 0,
                    last_scan=state.finished_at if state else None,
                )
            )
        return out

    # -- re-parsing --------------------------------------------------------------------------------

    def reparse(self, root_id: str | None = None, cancel: threading.Event | None = None) -> int:
        """Run the parsers again over the stored chunks; a file is re-read only when a chunk was truncated."""
        where, params = ("root_id = ?", [root_id]) if root_id else ("1", [])
        ids = [r["id"] for r in self.db.fetchall(f"SELECT id FROM images WHERE {where} ORDER BY id", params)]
        done = 0
        for start in range(0, len(ids), 200):
            if cancel is not None and cancel.is_set():
                break
            batch = []
            for image_id in ids[start : start + 200]:
                row = self.db.fetchone("SELECT * FROM images WHERE id = ?", (image_id,))
                if row is None:
                    continue
                raw, truncated = self._stored_raw(row)
                if truncated or not raw.chunks:
                    try:
                        path = self.library.file_path(row["root_id"], row["rel_path"])
                        raw = self.metadata.read_raw(path)
                    except (HanaikadaError, OSError):
                        pass
                batch.append((row, self.metadata.parse(raw, row["name"])))
            with self._write_lock, self.db.transaction() as conn:
                for row, parsed in batch:
                    values = records.image_values(row["root_id"], row["rel_path"], row["size"], row["mtime_ns"], row["ctime_ns"], parsed)
                    values["missing_since"] = row["missing_since"]
                    if not parsed.raw.chunks:
                        values["width"], values["height"], values["format"] = row["width"], row["height"], row["format"]
                    records.upsert_image(conn, values)
                    if parsed.raw.chunks:
                        records.replace_text(conn, row["id"], parsed, self.settings.settings.index.max_raw_bytes)
                    records.set_auto_tags(conn, self.tags, row["id"], derive_tags(parsed.info, values["width"], values["height"]))
                    done += 1
        with self._write_lock, self.db.transaction() as conn:
            records.delete_empty_auto_tags(conn)
        self.tags.clear()
        return done

    # -- tags ----------------------------------------------------------------------------------------

    def list_tags(self, tag_type: str | None = None, q: str | None = None, limit: int = 500, include_rare: bool = False) -> list[Tag]:
        clauses = []
        params: list[Any] = []
        if tag_type:
            if tag_type not in TAG_TYPES:
                raise ValidationError(f"Unknown tag type: {tag_type}")
            clauses.append("type = ?")
            params.append(tag_type)
        if q:
            clauses.append("name LIKE ? ESCAPE '\\'")
            params.append("%" + q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%")
        if not include_rare:
            clauses.append("(type != 'prompt' OR count >= ?)")
            params.append(self.settings.settings.index.prompt_tag_min_count)
        clauses.append("(count > 0 OR type IN ('custom', 'board'))")
        rows = self.db.fetchall(
            f"SELECT * FROM tags WHERE {' AND '.join(clauses)} ORDER BY type = 'custom' DESC, count DESC, name LIMIT ?",
            [*params, max(1, min(limit, 5000))],
        )
        return [records.tag_from_row(r) for r in rows]

    def get_tag(self, tag_id: int) -> Tag:
        row = self.db.fetchone("SELECT * FROM tags WHERE id = ?", (tag_id,))
        if row is None:
            raise NotFoundError(f"No tag with id {tag_id}")
        return records.tag_from_row(row)

    def find_tag(self, name: str, tag_type: str | None = None) -> Tag:
        """A tag by name: a custom tag first, then any type."""
        if tag_type:
            row = self.db.fetchone("SELECT * FROM tags WHERE name = ? AND type = ?", (name, tag_type))
        else:
            row = self.db.fetchone("SELECT * FROM tags WHERE name = ? ORDER BY type = 'custom' DESC, count DESC LIMIT 1", (name,))
        if row is None:
            raise NotFoundError(f"No tag named {name!r}")
        return records.tag_from_row(row)

    def create_tag(self, req: TagCreate) -> Tag:
        name = req.name.strip()
        if not name or len(name) > 100:
            raise ValidationError("A tag name must have 1 to 100 characters")
        if self.db.fetchone("SELECT 1 FROM tags WHERE name = ? AND type = 'custom'", (name,)):
            raise ConflictError(f"A tag named {name!r} exists")
        cursor = self.db.execute("INSERT INTO tags(name, type, color) VALUES (?, 'custom', ?)", (name, req.color))
        tag = self.get_tag(int(cursor.lastrowid or 0))
        self.events.publish(TagsChangedEvent(tag_ids=[tag.id]))
        self.backup_custom_tags()
        return tag

    def update_tag(self, tag_id: int, req: TagUpdate) -> Tag:
        tag = self.get_tag(tag_id)
        changes = req.model_dump(exclude_unset=True)
        if "name" in changes:
            if tag.type != "custom":
                raise ValidationError("Only custom tags can be renamed")
            name = (changes["name"] or "").strip()
            if not name or len(name) > 100:
                raise ValidationError("A tag name must have 1 to 100 characters")
            clash = self.db.fetchone("SELECT id FROM tags WHERE name = ? AND type = 'custom' AND id != ?", (name, tag_id))
            if clash:
                raise ConflictError(f"A tag named {name!r} exists")
            self.db.execute("UPDATE tags SET name = ? WHERE id = ?", (name, tag_id))
        if "color" in changes:
            self.db.execute("UPDATE tags SET color = ? WHERE id = ?", (changes["color"], tag_id))
        self.tags.forget(tag_id)
        self.events.publish(TagsChangedEvent(tag_ids=[tag_id]))
        self.backup_custom_tags()
        return self.get_tag(tag_id)

    def delete_tag(self, tag_id: int) -> None:
        tag = self.get_tag(tag_id)
        if tag.type != "custom":
            raise ValidationError("Only custom tags can be deleted")
        self.db.execute("DELETE FROM tags WHERE id = ?", (tag_id,))
        self.tags.forget(tag_id)
        self.events.publish(TagsChangedEvent(tag_ids=[tag_id]))
        self.backup_custom_tags()

    def _resolve_images(self, req: TagImagesRequest) -> list[int]:
        ids = list(req.image_ids)
        for root_id, rel in req.paths:
            record = self.record_by_path(root_id, rel)
            if record is None:
                record = self.index_file(root_id, rel)
            ids.append(record.id)
        return ids

    def tag_images(self, tag_id: int, req: TagImagesRequest, add: bool = True) -> TagOperationResult:
        tag = self.get_tag(tag_id)
        if tag.type not in ("custom",):
            raise ValidationError("Only custom tags can be added or removed by hand")
        ids = self._resolve_images(req)
        stamp = now_iso()
        with self._write_lock, self.db.transaction() as conn:
            if add:
                cursor = conn.executemany(
                    "INSERT OR IGNORE INTO image_tags(image_id, tag_id, created_at) SELECT id, ?, ? FROM images WHERE id = ?", [(tag_id, stamp, i) for i in ids]
                )
            else:
                cursor = conn.executemany("DELETE FROM image_tags WHERE image_id = ? AND tag_id = ?", [(i, tag_id) for i in ids])
            # rowcount leaves out the rows the count triggers touch.
            changed = max(cursor.rowcount, 0)
        self.events.publish(TagsChangedEvent(tag_ids=[tag_id]))
        self._changed_images(ids)
        self.backup_custom_tags()
        return TagOperationResult(tag=self.get_tag(tag_id), changed=changed)

    def _changed_images(self, ids: list[int]) -> None:
        by_dir: dict[tuple[str, str], list[str]] = {}
        for start in range(0, len(ids), 500):
            chunk = ids[start : start + 500]
            for r in self.db.fetchall(f"SELECT root_id, dir, rel_path FROM images WHERE id IN ({', '.join('?' for _ in chunk)})", chunk):
                by_dir.setdefault((r["root_id"], r["dir"]), []).append(r["rel_path"])
        for (root_id, rel_dir), rels in by_dir.items():
            self._changed(root_id, rel_dir, updated=rels)

    def image_tags(self, image_id: int) -> list[Tag]:
        self._row(image_id)
        return [
            records.tag_from_row(t)
            for t in self.db.fetchall("SELECT t.* FROM tags t JOIN image_tags it ON it.tag_id = t.id WHERE it.image_id = ? ORDER BY t.type, t.name", (image_id,))
        ]

    # -- custom tag backup ------------------------------------------------------------------------

    def backup_custom_tags(self) -> None:
        """Write every custom tag and the paths it is on, so a deleted database keeps them."""
        tags = self.db.fetchall("SELECT id, name, color FROM tags WHERE type = 'custom' ORDER BY id")
        data: dict[str, Any] = {"version": 1, "tags": []}
        for tag in tags:
            paths = [
                f"{r['root_id']}:{r['rel_path']}"
                for r in self.db.fetchall("SELECT i.root_id, i.rel_path FROM images i JOIN image_tags it ON it.image_id = i.id WHERE it.tag_id = ?", (tag["id"],))
            ]
            data["tags"].append({"name": tag["name"], "color": tag["color"], "paths": paths})
        path = self.settings.data_dir / TAGS_BACKUP_FILE
        tmp = path.with_suffix(".json.tmp")
        try:
            tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
            tmp.replace(path)
        except OSError as e:
            logger.warning("Could not write %s: %s", path, e)

    def restore_custom_tags(self) -> int:
        """Apply the backup to the images indexed so far. Runs after scans until every path was found."""
        path = self.settings.data_dir / TAGS_BACKUP_FILE
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            self.db.set_client_state(RESTORE_KEY, False)
            return 0
        applied = 0
        pending = 0
        stamp = now_iso()
        with self._write_lock, self.db.transaction() as conn:
            for entry in data.get("tags", []):
                name = entry.get("name")
                if not isinstance(name, str):
                    continue
                row = conn.execute("SELECT id FROM tags WHERE name = ? AND type = 'custom'", (name,)).fetchone()
                tag_id = row["id"] if row else conn.execute("INSERT INTO tags(name, type, color) VALUES (?, 'custom', ?)", (name, entry.get("color"))).lastrowid
                for ref in entry.get("paths", []):
                    root_id, _, rel = str(ref).partition(":")
                    image = conn.execute("SELECT id FROM images WHERE root_id = ? AND rel_path = ?", (root_id, rel)).fetchone()
                    if image is None:
                        pending += 1
                        continue
                    applied += conn.execute("INSERT OR IGNORE INTO image_tags(image_id, tag_id, created_at) VALUES (?, ?, ?)", (image["id"], tag_id, stamp)).rowcount
        if pending == 0 or not any(job.kind == "root" for job in self.scanner.queued()):
            self.db.set_client_state(RESTORE_KEY, False)
        if applied:
            self.events.publish(TagsChangedEvent())
        return applied

    # -- InvokeAI boards ----------------------------------------------------------------------------

    def import_invokeai_boards(self, root_id: str, plan: LayoutPlan) -> int:
        """Boards, stars and intermediates from InvokeAI's database, as board tags. Read-only."""
        assert plan.invokeai_db is not None
        output = plan.outputs[0].rel if plan.outputs else ""
        uri = plan.invokeai_db.resolve().as_uri() + "?mode=ro"
        source = sqlite3.connect(uri, uri=True)
        try:
            source.row_factory = sqlite3.Row
            columns = {r["name"] for r in source.execute("PRAGMA table_info(images)")}
            subfolder = "image_subfolder" if "image_subfolder" in columns else "NULL"
            starred = "starred" if "starred" in columns else "0"
            rows = source.execute(
                f"SELECT i.image_name, {subfolder} AS subfolder, {starred} AS starred, i.is_intermediate, b.board_name "
                "FROM images i LEFT JOIN board_images bi ON bi.image_name = i.image_name LEFT JOIN boards b ON b.board_id = bi.board_id"
            ).fetchall()
        finally:
            source.close()
        links: list[tuple[str, str]] = []
        for r in rows:
            parts = [p for p in (output, r["subfolder"] or "", r["image_name"]) if p]
            rel = "/".join(parts)
            if r["board_name"]:
                links.append((rel, r["board_name"]))
            if r["starred"]:
                links.append((rel, "starred"))
            if r["is_intermediate"]:
                links.append((rel, "intermediate"))
        stamp = now_iso()
        with self._write_lock, self.db.transaction() as conn:
            conn.execute("DELETE FROM image_tags WHERE tag_id IN (SELECT id FROM tags WHERE type = 'board') AND image_id IN (SELECT id FROM images WHERE root_id = ?)", (root_id,))
            added = 0
            for rel, board in links:
                image = conn.execute("SELECT id FROM images WHERE root_id = ? AND rel_path = ?", (root_id, rel)).fetchone()
                if image is None:
                    continue
                tag_id = self.tags.ensure(conn, board, "board")
                added += conn.execute("INSERT OR IGNORE INTO image_tags(image_id, tag_id, created_at) VALUES (?, ?, ?)", (image["id"], tag_id, stamp)).rowcount
            conn.execute("DELETE FROM tags WHERE type = 'board' AND count <= 0")
        self.tags.clear()
        return added

    def ids_for_paths(self, refs: Iterable[tuple[str, str]]) -> list[int]:
        out = []
        for root_id, rel in refs:
            row = self.db.fetchone("SELECT id FROM images WHERE root_id = ? AND rel_path = ?", (root_id, rel))
            if row is not None:
                out.append(row["id"])
        return out
