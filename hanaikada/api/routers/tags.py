"""Tags: custom ones, and those derived from metadata."""

from fastapi import APIRouter, Query, status

from hanaikada.api.deps import ServicesDep
from hanaikada.api.errors import ERROR_RESPONSES
from hanaikada.core.index.models import Tag, TagCreate, TagImagesRequest, TagOperationResult, TagType, TagUpdate

router = APIRouter(prefix="/v1", tags=["tags"], responses=ERROR_RESPONSES)


@router.get("/tags", operation_id="list_tags")
def list_tags(
    services: ServicesDep,
    type: TagType | None = None,
    q: str | None = None,
    limit: int = Query(default=500, ge=1, le=5000),
    include_rare: bool = Query(default=False, description="Also prompt tags below index.prompt_tag_min_count"),
) -> list[Tag]:
    return services.index.list_tags(type, q, limit, include_rare)


@router.post("/tags", operation_id="create_tag", status_code=status.HTTP_201_CREATED)
def create_tag(services: ServicesDep, body: TagCreate) -> Tag:
    return services.index.create_tag(body)


@router.patch("/tags/{tag_id}", operation_id="update_tag")
def update_tag(services: ServicesDep, tag_id: int, body: TagUpdate) -> Tag:
    return services.index.update_tag(tag_id, body)


@router.delete("/tags/{tag_id}", operation_id="delete_tag", status_code=status.HTTP_204_NO_CONTENT)
def delete_tag(services: ServicesDep, tag_id: int) -> None:
    services.index.delete_tag(tag_id)


@router.post("/tags/{tag_id}/images", operation_id="add_tag_to_images")
def add_tag_to_images(services: ServicesDep, tag_id: int, body: TagImagesRequest) -> TagOperationResult:
    return services.index.tag_images(tag_id, body, add=True)


@router.delete("/tags/{tag_id}/images", operation_id="remove_tag_from_images")
def remove_tag_from_images(services: ServicesDep, tag_id: int, body: TagImagesRequest) -> TagOperationResult:
    return services.index.tag_images(tag_id, body, add=False)


@router.get("/images/{image_id}/tags", operation_id="get_image_tags")
def get_image_tags(services: ServicesDep, image_id: int) -> list[Tag]:
    return services.index.image_tags(image_id)
