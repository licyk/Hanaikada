"""Roots, folder listings, files, thumbnails and file operations."""

from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, Query, Request, status
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import Response, StreamingResponse
from starlette.requests import ClientDisconnect

from hanaikada.api.deps import ServicesDep
from hanaikada.api.errors import ERROR_RESPONSES
from hanaikada.api.files import cached_file, content_disposition
from hanaikada.core.errors import HanaikadaError
from hanaikada.core.library.models import (
    CombinedListing,
    CoverImage,
    DeleteRequest,
    FolderCreate,
    FolderListing,
    LayoutSuggestion,
    ListSort,
    OpenRequest,
    OperationResult,
    PathRef,
    RenameRequest,
    RootCreate,
    RootInfo,
    RootUpdate,
    ThumbnailCacheInfo,
    TransferRequest,
    TreeNode,
    ZipRequest,
)
from hanaikada.core.net.ports import is_loopback

router = APIRouter(prefix="/v1/library", tags=["library"], responses=ERROR_RESPONSES)

IMAGE_RESPONSES: dict[int | str, dict[str, Any]] = {200: {"content": {"image/webp": {}, "image/*": {}}}, 304: {"description": "Not modified"}}


class NotLocalError(HanaikadaError):
    code = "not_local"
    http_status = 403
    exit_code = 4


@router.get("/roots", operation_id="list_roots")
def list_roots(services: ServicesDep) -> list[RootInfo]:
    return services.library.list_roots()


@router.get("/detect-layout", operation_id="detect_layout")
def detect_layout(services: ServicesDep, path: str = Query(description="Absolute folder path on the server")) -> LayoutSuggestion:
    """Suggest a layout for a folder before adding it as a root."""
    return services.library.suggest_layout(path)


@router.post("/roots", operation_id="add_root", status_code=status.HTTP_201_CREATED)
def add_root(services: ServicesDep, body: RootCreate) -> RootInfo:
    """Add a root. With ``layout: auto`` the layout is detected from the folder."""
    return services.library.add_root(body)


@router.patch("/roots/{root_id}", operation_id="update_root")
def update_root(services: ServicesDep, root_id: str, body: RootUpdate) -> RootInfo:
    return services.library.update_root(root_id, body)


@router.delete("/roots/{root_id}", operation_id="remove_root", status_code=status.HTTP_204_NO_CONTENT)
def remove_root(services: ServicesDep, root_id: str) -> None:
    services.library.remove_root(root_id)


@router.get("/combined/entries", operation_id="list_combined_entries")
def list_combined_entries(services: ServicesDep) -> CombinedListing:
    """Every root's output folders side by side, as folders; ``library.combined_view`` only decides whether the interface offers it."""
    return services.library.list_combined()


@router.get("/roots/{root_id}/entries", operation_id="list_entries")
def list_entries(
    services: ServicesDep,
    root_id: str,
    path: str = "",
    sort: ListSort = "mtime",
    desc: bool = True,
    cursor: str | None = None,
    limit: int = Query(default=500, ge=1, le=5000),
    seed: int | None = None,
) -> FolderListing:
    """A folder: subfolders with covers, then a page of files joined with the index."""
    return services.library.list_entries(root_id, path, sort=sort, descending=desc, cursor=cursor, limit=limit, random_seed=seed)


@router.get("/roots/{root_id}/tree", operation_id="get_tree")
def get_tree(services: ServicesDep, root_id: str, path: str = "", depth: int = Query(default=1, ge=0, le=8)) -> TreeNode:
    return services.library.tree(root_id, path, depth)


@router.get("/roots/{root_id}/file", operation_id="get_file", response_class=Response, responses=IMAGE_RESPONSES)
def get_file(request: Request, services: ServicesDep, root_id: str, path: str, t: str | None = None, download: bool = False) -> Response:
    """The file itself. With ``t`` (the mtime token of its listing) it may be cached for a year."""
    target = services.library.file_path(root_id, path)
    return cached_file(request, target, versioned=bool(t), download_name=target.name if download else None, inline_name=None if download else target.name)


@router.get("/roots/{root_id}/thumbnail", operation_id="get_thumbnail", response_class=Response, responses=IMAGE_RESPONSES)
def get_thumbnail(request: Request, services: ServicesDep, root_id: str, path: str, size: int = Query(default=256, ge=1, le=2048), t: str | None = None) -> Response:
    thumb = services.library.thumbnail(root_id, path, size)
    return cached_file(request, thumb.path, etag=thumb.etag, media_type=thumb.media_type, versioned=bool(t))


@router.get("/roots/{root_id}/cover", operation_id="get_cover")
def get_cover(services: ServicesDep, root_id: str, path: str = "") -> list[CoverImage]:
    """Up to four newest images directly in a folder."""
    return services.library.cover(root_id, path)


@router.get("/thumbnails", operation_id="get_thumbnail_cache")
def get_thumbnail_cache(services: ServicesDep) -> ThumbnailCacheInfo:
    return services.library.thumbnail_cache()


@router.post("/thumbnails/clear", operation_id="clear_thumbnail_cache")
def clear_thumbnail_cache(services: ServicesDep) -> ThumbnailCacheInfo:
    return services.library.clear_thumbnail_cache()


@router.get("/locate", operation_id="locate_path")
def locate_path(services: ServicesDep, path: str = Query(description="Absolute path on the server")) -> PathRef:
    """The root that holds an absolute path, so a client can open it."""
    return services.library.locate(Path(path))


@router.post("/move", operation_id="move_items")
def move_items(services: ServicesDep, body: TransferRequest) -> OperationResult:
    return services.library.transfer(body, copy=False)


@router.post("/copy", operation_id="copy_items")
def copy_items(services: ServicesDep, body: TransferRequest) -> OperationResult:
    return services.library.transfer(body, copy=True)


@router.post("/rename", operation_id="rename_item")
def rename_item(services: ServicesDep, body: RenameRequest) -> OperationResult:
    return services.library.rename(body)


@router.post("/delete", operation_id="delete_items")
def delete_items(services: ServicesDep, body: DeleteRequest) -> OperationResult:
    return services.library.delete(body)


@router.post("/folders", operation_id="create_folder", status_code=status.HTTP_201_CREATED)
def create_folder(services: ServicesDep, body: FolderCreate) -> PathRef:
    return services.library.create_folder(body)


@router.put(
    "/upload",
    operation_id="upload_file",
    status_code=status.HTTP_201_CREATED,
    openapi_extra={"requestBody": {"content": {"application/octet-stream": {"schema": {"type": "string", "format": "binary"}}}, "required": True}},
)
async def upload_file(
    request: Request,
    services: ServicesDep,
    root_id: str,
    name: str = Query(description="File name; may contain '/' to keep a dropped folder's structure"),
    path: str = Query(default="", description="Destination folder inside the root"),
    on_conflict: Literal["error", "rename"] = "error",
) -> PathRef:
    """Stream the raw request body into the destination, then index the file."""
    length = request.headers.get("content-length")
    total = int(length) if length and length.isdigit() else None
    writer = await run_in_threadpool(services.library.open_upload, root_id, path, name, total, on_conflict)
    try:
        async for chunk in request.stream():
            if chunk:
                await run_in_threadpool(writer.write, chunk)
    except (ClientDisconnect, Exception):
        await run_in_threadpool(writer.abort)
        raise
    return await run_in_threadpool(writer.commit)


@router.post("/open", operation_id="open_in_file_manager", status_code=status.HTTP_204_NO_CONTENT)
def open_in_file_manager(request: Request, services: ServicesDep, body: OpenRequest) -> None:
    """Show a file in the file manager, or open it with its default application: only from the server's own machine."""
    client = request.client.host if request.client else ""
    if not (is_loopback(client) or client == "testclient"):
        raise NotLocalError("Opening files works only in a browser on the server's own machine")
    services.library.open_in_file_manager(body)


@router.post("/zip", operation_id="download_zip", response_class=StreamingResponse, responses={200: {"content": {"application/zip": {}}}})
def download_zip(services: ServicesDep, body: ZipRequest) -> StreamingResponse:
    """A zip of the selected files and folders, streamed while it is made."""
    stream = services.library.zip_stream(body.items)
    name = (body.name or "hanaikada") + ".zip"
    return StreamingResponse(stream, media_type="application/zip", headers={"Content-Disposition": content_disposition("attachment", name)})
