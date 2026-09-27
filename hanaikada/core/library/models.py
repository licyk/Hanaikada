"""Library records returned by the service."""

from datetime import datetime
from typing import Literal

from pydantic import Field

from hanaikada.core.index.models import ImageRecord
from hanaikada.core.record import Record
from hanaikada.core.settings.models import LayoutName

EntryKind = Literal["image", "video", "audio", "file"]
ListSort = Literal["name", "mtime", "ctime", "size", "random"]


class RootInfo(Record):
    id: str
    name: str
    path: str
    layout: LayoutName
    enabled: bool
    index: bool
    exists: bool
    outputs: list[str] = Field(default_factory=list)
    """The folders this root's layout indexes, relative to it."""


class RootCreate(Record):
    path: str
    name: str | None = None
    layout: LayoutName | Literal["auto"] = "auto"
    enabled: bool = True
    index: bool = True


class RootUpdate(Record):
    name: str | None = None
    path: str | None = None
    layout: LayoutName | None = None
    enabled: bool | None = None
    index: bool | None = None


class LayoutSuggestion(Record):
    layout: LayoutName
    reason: str


class CoverImage(Record):
    path: str
    version: str
    """The file's mtime in nanoseconds, as text: the cache token in thumbnail URLs."""


class FolderEntry(Record):
    name: str
    path: str
    mtime: datetime | None = None
    label: str | None = None
    cover: list[CoverImage] = Field(default_factory=list)


class FileEntry(Record):
    name: str
    path: str
    kind: EntryKind
    size: int
    mtime: datetime
    ctime: datetime | None = None
    version: str
    indexed: bool = False
    image: ImageRecord | None = None


class FolderListing(Record):
    root_id: str
    path: str
    label: str | None = None
    folders: list[FolderEntry]
    files: list[FileEntry]
    total_files: int
    next_cursor: str | None = None


COMBINED_VIEW_ID = "*"
"""Stands for "every root" in the interface's root selector, so no root may use it as its id."""


class CombinedFolder(FolderEntry):
    """One entry of "All folders": an output folder of a root, or a root that is itself its output folder."""

    root_id: str
    root_name: str
    display_name: str
    """The name, or ``name (root name)`` when another entry has the same name."""
    is_root: bool
    """The root itself (its ``path`` is ``""``), named after the root: it cannot be moved, renamed or deleted."""


class CombinedListing(Record):
    """The output folders of every root side by side, as folders only; no file is ever loose here."""

    folders: list[CombinedFolder]
    missing_roots: list[str] = Field(default_factory=list)
    """Roots whose folder does not exist or cannot be read, left out rather than failing the whole listing."""


class TreeNode(Record):
    name: str
    path: str
    label: str | None = None
    has_children: bool = False
    children: list["TreeNode"] = Field(default_factory=list)


class PathRef(Record):
    root_id: str
    path: str


class TransferRequest(Record):
    """Move or copy files and folders into one destination folder."""

    items: list[PathRef]
    dest_root_id: str
    dest_dir: str = ""
    on_conflict: Literal["error", "rename", "skip"] = "error"
    continue_on_error: bool = False


class RenameRequest(Record):
    root_id: str
    path: str
    new_name: str


class DeleteRequest(Record):
    items: list[PathRef]
    permanent: bool = False


class FolderCreate(Record):
    root_id: str
    path: str = ""
    name: str


class OperationError(Record):
    root_id: str
    path: str
    code: str
    message: str


class OperationResult(Record):
    """Paths affected by an operation, relative to their roots."""

    paths: list[PathRef] = Field(default_factory=list)
    trashed_to: list[str] = Field(default_factory=list)
    errors: list[OperationError] = Field(default_factory=list)
    skipped: list[PathRef] = Field(default_factory=list)


class OpenRequest(Record):
    root_id: str
    path: str = ""
    reveal: bool = True
    """True: show the file in the file manager. False: open it with the default application."""


class ThumbnailCacheInfo(Record):
    files: int
    bytes: int
    max_bytes: int
    path: str


class ZipRequest(Record):
    items: list[PathRef]
    name: str | None = None
