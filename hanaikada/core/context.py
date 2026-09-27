"""Build every service once. The API and the command line both start here."""

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from hanaikada.core.db import Database
from hanaikada.core.events import EventBus, LocalEventBus
from hanaikada.core.index import IndexService
from hanaikada.core.library import LibraryService
from hanaikada.core.library.thumbnails import ThumbnailService
from hanaikada.core.metadata import MetadataService
from hanaikada.core.settings import SettingsService

DB_FILE_NAME = "hanaikada.db"
THUMBNAIL_DIR = "thumbnails"


@dataclass
class Services:
    settings: SettingsService
    events: EventBus
    db: Database
    library: LibraryService
    metadata: MetadataService
    index: IndexService

    def close(self) -> None:
        self.index.close()
        self.db.close()


def build_services(
    data_dir: Path | None = None,
    settings_path: Path | None = None,
    environ: dict[str, str] | None = None,
    settings_overrides: dict[str, Any] | None = None,
    roots_locked: bool = False,
    start_scanner: bool = False,
) -> Services:
    """Create all services.

    ``start_scanner`` is false for the command line, which scans in the foreground, and true for
    the server. ``settings_overrides`` and ``roots_locked`` come from a host application embedding
    this package; ``environ`` replaces ``os.environ`` in tests.
    """
    settings = SettingsService(data_dir=data_dir, settings_path=settings_path, environ=environ, overrides=settings_overrides)
    events = LocalEventBus()
    db = Database(settings.data_dir / DB_FILE_NAME)
    thumbnails = ThumbnailService(settings.data_dir / THUMBNAIL_DIR, quality=settings.settings.thumbnails.quality)
    library = LibraryService(settings, events, thumbnails, roots_locked=roots_locked)
    metadata = MetadataService(settings)
    index = IndexService(settings, db, events, library, metadata, thumbnails)
    services = Services(settings=settings, events=events, db=db, library=library, metadata=metadata, index=index)
    if start_scanner:
        thumbnails.sweep(settings.settings.thumbnails.cache_max_mb * 1024 * 1024)
        index.start()
    return services
