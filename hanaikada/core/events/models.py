"""Event models. Each has an event name and is published on the EventBus.

Every event carries a snapshot, never a live object: the socket bridge serialises it later, on
the event loop, while the scanner keeps working.
"""

from typing import ClassVar

from pydantic import Field

from hanaikada.core.record import Record


class EventBase(Record):
    __event_name__: ClassVar[str] = ""

    @classmethod
    def get_events(cls) -> list[type["EventBase"]]:
        """Every concrete event class, for the OpenAPI schema."""
        out: list[type[EventBase]] = []
        stack = list(cls.__subclasses__())
        while stack:
            sub = stack.pop()
            stack.extend(sub.__subclasses__())
            if sub.__event_name__:
                out.append(sub)
        return sorted(out, key=lambda c: c.__event_name__)


class ScanStartedEvent(EventBase):
    __event_name__ = "scan_started"
    root_id: str
    full: bool


class ScanProgressEvent(EventBase):
    __event_name__ = "scan_progress"
    root_id: str
    folders_seen: int
    files_seen: int
    files_indexed: int
    files_failed: int
    current: str | None = None


class ScanCompletedEvent(EventBase):
    __event_name__ = "scan_completed"
    root_id: str
    folders_seen: int
    files_seen: int
    files_indexed: int
    files_failed: int
    files_missing: int = 0
    cancelled: bool = False


class ScanFailedEvent(EventBase):
    __event_name__ = "scan_failed"
    root_id: str
    files_indexed: int
    error: str


class IndexChangedEvent(EventBase):
    __event_name__ = "index_changed"
    root_id: str
    rel_dir: str
    added: list[str] = Field(default_factory=list)
    updated: list[str] = Field(default_factory=list)
    removed: list[str] = Field(default_factory=list)
    more: bool = False
    """True when more paths changed than the lists carry (they are capped at 200)."""


class LibraryChangedEvent(EventBase):
    __event_name__ = "library_changed"
    root_id: str
    rel_path: str = ""


class TagsChangedEvent(EventBase):
    __event_name__ = "tags_changed"
    tag_ids: list[int] = Field(default_factory=list)


class ImportProgressEvent(EventBase):
    __event_name__ = "import_progress"
    root_id: str
    rel_path: str
    bytes_done: int
    total_bytes: int | None
    done: bool = False
