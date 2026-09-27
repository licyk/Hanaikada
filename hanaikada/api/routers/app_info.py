"""App version, health and what the interface needs to know about this server."""

from fastapi import APIRouter, Request

from hanaikada.api.deps import ServicesDep
from hanaikada.core.library.thumbnails import ALLOWED_SIZES
from hanaikada.core.metadata.models import PLATFORMS
from hanaikada.core.net.ports import is_loopback
from hanaikada.core.record import Record
from hanaikada.version import VERSION

router = APIRouter(prefix="/v1/app", tags=["app"])


class AppVersion(Record):
    version: str


class Health(Record):
    status: str
    auth_required: bool


class AppMeta(Record):
    roots_locked: bool
    """True when a host application supplies the image folders; the interface then hides adding,
    editing and removing them."""
    fts: bool
    """Whether text search uses SQLite's full-text index; without it, a slower LIKE is used."""
    local: bool
    """Whether this request comes from the server's own machine: only then can it open the file manager."""
    platforms: list[str]
    layouts: list[str]
    thumbnail_sizes: list[int]
    trash_location: str
    api_prefix: str
    data_dir: str


@router.get("/version", operation_id="get_app_version")
def get_version() -> AppVersion:
    return AppVersion(version=VERSION)


@router.get("/health", operation_id="get_health")
def get_health(services: ServicesDep) -> Health:
    return Health(status="ok", auth_required=bool(services.settings.settings.server.access_token))


@router.get("/meta", operation_id="get_app_meta")
def get_meta(request: Request, services: ServicesDep) -> AppMeta:
    client = request.client.host if request.client else ""
    return AppMeta(
        roots_locked=services.library.roots_locked,
        fts=services.db.fts,
        local=bool(client) and (is_loopback(client) or client == "testclient"),
        platforms=PLATFORMS,
        layouts=["sd-webui", "comfyui", "invokeai", "custom"],
        thumbnail_sizes=list(ALLOWED_SIZES),
        trash_location=services.library.trash_location(),
        api_prefix=getattr(request.app.state, "api_prefix", "") or "",
        data_dir=str(services.settings.data_dir),
    )
