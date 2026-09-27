"""One image: its detail, raw chunks, similar images; and parsing an uploaded file."""

from typing import Literal

from fastapi import APIRouter, Query, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import Response

from hanaikada.api.deps import ServicesDep
from hanaikada.api.errors import ERROR_RESPONSES
from hanaikada.api.files import content_disposition
from hanaikada.core.errors import ValidationError
from hanaikada.core.index.models import ImageDetail, SearchPage
from hanaikada.core.metadata.views import ParseResult, RawView, parse_result

router = APIRouter(prefix="/v1/images", tags=["images"], responses=ERROR_RESPONSES)

MAX_PARSE_BYTES = 256 * 1024 * 1024


@router.get("/by-path", operation_id="get_image_by_path")
def get_image_by_path(services: ServicesDep, root_id: str, path: str) -> ImageDetail:
    """The image at a path, indexed on demand when the index does not know it or is behind."""
    return services.index.by_path(root_id, path)


@router.post(
    "/parse",
    operation_id="parse_image",
    openapi_extra={"requestBody": {"content": {"application/octet-stream": {"schema": {"type": "string", "format": "binary"}}}, "required": True}},
)
async def parse_image(
    request: Request, services: ServicesDep, name: str | None = Query(default=None, description="The file's name, which helps pick ComfyUI's save node")
) -> ParseResult:
    """Parse an uploaded file without storing it: the PNG Info tab."""
    data = bytearray()
    async for chunk in request.stream():
        data.extend(chunk)
        if len(data) > MAX_PARSE_BYTES:
            raise ValidationError("File too large to parse")
    parsed = await run_in_threadpool(services.metadata.read_bytes, bytes(data), name)
    return parse_result(parsed)


@router.get("/{image_id}", operation_id="get_image")
def get_image(services: ServicesDep, image_id: int) -> ImageDetail:
    return services.index.detail(image_id)


@router.get("/{image_id}/raw", operation_id="get_image_raw")
def get_image_raw(services: ServicesDep, image_id: int) -> RawView:
    """Every text chunk whole, and every container and EXIF entry."""
    return services.index.raw(image_id)


@router.get("/{image_id}/raw/{key}", operation_id="download_image_chunk", response_class=Response, responses={200: {"content": {"application/json": {}, "text/plain": {}}}})
def download_image_chunk(services: ServicesDep, image_id: int, key: str, inline: bool = False) -> Response:
    """One chunk as a file: a ComfyUI workflow as ``.json`` to drop back into ComfyUI, an infotext as ``.txt``."""
    value, filename = services.index.chunk(image_id, key)
    media_type = "application/json" if filename.endswith(".json") else "text/plain; charset=utf-8"
    return Response(value.encode("utf-8"), media_type=media_type, headers={"Content-Disposition": content_disposition("inline" if inline else "attachment", filename)})


@router.get("/{image_id}/similar", operation_id="get_similar_images")
def get_similar_images(services: ServicesDep, image_id: int, by: Literal["seed", "model", "prompt"] = "seed", limit: int = Query(default=200, ge=1, le=1000)) -> SearchPage:
    return services.index.similar(image_id, by, limit)
