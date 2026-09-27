"""Search, random picks, facets and statistics."""

from typing import Annotated

from fastapi import APIRouter, Query

from hanaikada.api.deps import ServicesDep
from hanaikada.api.errors import ERROR_RESPONSES
from hanaikada.core.index.models import Facets, SearchPage, SearchQuery, Stats

router = APIRouter(prefix="/v1/search", tags=["search"], responses=ERROR_RESPONSES)


@router.post("", operation_id="search_images")
def search_images(services: ServicesDep, body: SearchQuery) -> SearchPage:
    """A page of images matching every filter given, with a cursor for the next page."""
    return services.index.search(body)


@router.get("/random", operation_id="random_images")
def random_images(services: ServicesDep, limit: int = Query(default=128, ge=1, le=1000)) -> SearchPage:
    return services.index.random(limit)


@router.post("/facets", operation_id="search_facets")
def search_facets(services: ServicesDep, body: SearchQuery) -> Facets:
    """Counts per platform, model, sampler and size for the images the query matches."""
    return services.index.facets(body)


@router.get("/stats", operation_id="search_stats")
def search_stats(services: ServicesDep, root_id: Annotated[list[str] | None, Query()] = None) -> Stats:
    """Images per day and per month, and the most used platforms, models, samplers and LoRAs."""
    return services.index.stats(root_id)
