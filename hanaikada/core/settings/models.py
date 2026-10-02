"""Settings models."""

from typing import Literal

from pydantic import Field

from hanaikada.core.record import Record

LayoutName = Literal["sd-webui", "comfyui", "invokeai", "custom"]

DEFAULT_IMAGE_EXTENSIONS = [".png", ".jpg", ".jpeg", ".webp", ".avif", ".gif", ".jxl"]
DEFAULT_SIDECAR_EXTENSIONS = [".txt", ".json"]


class ServerSettings(Record):
    host: str = "127.0.0.1"
    port: int = Field(default=7867, ge=1, le=65535)
    strict_port: bool = False
    open_browser: bool = True
    access_token: str | None = None
    allowed_origins: list[str] = Field(default_factory=list)


class ImageRoot(Record):
    id: str
    name: str
    path: str
    layout: LayoutName = "custom"
    enabled: bool = True
    index: bool = True
    """False for a root that is only browsed: it has thumbnails and on-demand metadata, but the
    background scanner leaves it alone."""


class PathSettings(Record):
    roots: list[ImageRoot] = Field(default_factory=list)


class IndexSettings(Record):
    image_extensions: list[str] = Field(default_factory=lambda: list(DEFAULT_IMAGE_EXTENSIONS))
    follow_symlinks: bool = True
    # Seconds between polls of every known folder's mtime; 0 turns watching off.
    watch_interval: int = Field(default=30, ge=0)
    scan_on_start: bool = True
    include_comfyui_temp: bool = False
    invokeai_read_db: bool = True
    # A prompt token becomes a tag only once this many images share it.
    prompt_tag_min_count: int = Field(default=2, ge=1)
    # Larger chunks are stored truncated and re-read from the file on demand.
    max_raw_bytes: int = Field(default=4 * 1024 * 1024, ge=1024)


class ThumbnailSettings(Record):
    quality: int = Field(default=82, ge=1, le=100)
    cache_max_mb: int = Field(default=2048, ge=16)
    prefer_platform_thumbnails: bool = True
    pregenerate: bool = True


class LibrarySettings(Record):
    delete_to_trash: bool = True
    show_all_files: bool = False
    combined_view: bool = False
    """Offer "All folders" in Browse: the output folders of every root side by side."""
    sidecar_extensions: list[str] = Field(default_factory=lambda: list(DEFAULT_SIDECAR_EXTENSIONS))


class ContentSettings(Record):
    blur_tags: list[str] = Field(default_factory=list)


class Settings(Record):
    """Everything saved in ``settings.toml``."""

    server: ServerSettings = Field(default_factory=ServerSettings)
    paths: PathSettings = Field(default_factory=PathSettings)
    index: IndexSettings = Field(default_factory=IndexSettings)
    thumbnails: ThumbnailSettings = Field(default_factory=ThumbnailSettings)
    library: LibrarySettings = Field(default_factory=LibrarySettings)
    content: ContentSettings = Field(default_factory=ContentSettings)


# Public views: the access token never leaves the server.


class ServerSettingsView(Record):
    host: str
    port: int
    strict_port: bool
    open_browser: bool
    access_token_configured: bool
    allowed_origins: list[str]


class SettingsView(Record):
    """Settings as returned to clients, with the token replaced by a flag."""

    data_dir: str
    settings_file: str
    server: ServerSettingsView
    paths: PathSettings
    index: IndexSettings
    thumbnails: ThumbnailSettings
    library: LibrarySettings
    content: ContentSettings
    env_overrides: list[str]
    pinned: list[str]
    """Dotted names of the settings a host application pinned; changing them has no effect."""
