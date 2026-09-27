"""Index records: image rows, details, tags, search and scan status."""

from datetime import datetime
from typing import Literal

from pydantic import Field

from hanaikada.core.metadata.models import GenerationInfo
from hanaikada.core.record import BigInt, Record

TagType = Literal["custom", "prompt", "lora", "model", "sampler", "platform", "size", "board"]
TAG_TYPES: list[str] = ["custom", "prompt", "lora", "model", "sampler", "platform", "size", "board"]
SearchSort = Literal["mtime", "ctime", "name", "size", "seed", "random"]
TextField = Literal["prompt", "negative", "name", "model", "loras"]
PROMPT_EXCERPT = 400


class ImageRecord(Record):
    """One indexed image, as listings and search results show it."""

    id: int
    root_id: str
    path: str
    name: str
    ext: str
    size: int
    mtime: datetime
    version: str
    """The file's mtime in nanoseconds, as text: the cache token in file and thumbnail URLs."""
    width: int | None = None
    height: int | None = None
    format: str | None = None
    platform: str | None = None
    prompt: str | None = None
    """The positive prompt, cut to a few hundred characters; the detail has it whole."""
    seed: BigInt | None = None
    steps: int | None = None
    cfg_scale: float | None = None
    sampler: str | None = None
    sampler_norm: str | None = None
    model_name: str | None = None
    gen_width: int | None = None
    gen_height: int | None = None
    mode: str | None = None
    has_error: bool = False
    missing: bool = False
    tag_ids: list[int] = Field(default_factory=list)
    """Custom and board tags, for the dots on a grid cell."""
    blur: bool = False
    """True when one of ``content.blur_tags`` applies."""


class Tag(Record):
    id: int
    name: str
    type: TagType
    color: str | None = None
    count: int = 0


class TagCreate(Record):
    name: str
    color: str | None = None


class TagUpdate(Record):
    name: str | None = None
    color: str | None = None


class TagImagesRequest(Record):
    image_ids: list[int] = Field(default_factory=list)
    paths: list[tuple[str, str]] = Field(default_factory=list)
    """``(root_id, path)`` pairs, indexed on demand when not yet in the index."""


class TagOperationResult(Record):
    tag: Tag
    changed: int


class Neighbours(Record):
    previous: int | None = None
    next: int | None = None


class ImageDetail(Record):
    record: ImageRecord
    info: GenerationInfo
    prompt: str | None = None
    """The whole positive prompt."""
    parse_error: str | None = None
    tags: list[Tag] = Field(default_factory=list)
    companions: list[str] = Field(default_factory=list)
    chunks: list[str] = Field(default_factory=list)
    """Keys of the raw text chunks stored for this image."""
    neighbours: Neighbours = Field(default_factory=Neighbours)
    """The images before and after this one in its folder, newest first."""


class SearchQuery(Record):
    text: str | None = None
    """Substring over prompt, negative prompt, name, model and LoRAs (FTS trigram, or LIKE)."""
    text_in: list[TextField] | None = None
    regex: str | None = None
    """Applied in Python over the rows the other filters select, up to a cap."""
    root_ids: list[str] | None = None
    path_prefix: str | None = None
    """A folder, recursive. Needs exactly one root in ``root_ids``."""
    platforms: list[str] | None = None
    models: list[str] | None = None
    samplers: list[str] | None = None
    seed: BigInt | None = None
    steps: tuple[int | None, int | None] | None = None
    cfg: tuple[float | None, float | None] | None = None
    width: int | None = None
    height: int | None = None
    orientation: Literal["portrait", "landscape", "square"] | None = None
    date: tuple[str | None, str | None] | None = None
    """By file mtime: ISO dates or date-times, either end open."""
    all_tags: list[int] = Field(default_factory=list)
    any_tags: list[int] = Field(default_factory=list)
    not_tags: list[int] = Field(default_factory=list)
    include_missing: bool = False
    sort: SearchSort = "mtime"
    descending: bool = True
    random_seed: int | None = None
    """Fixes the order of ``sort = random`` so that paging through it is stable."""
    cursor: str | None = None
    limit: int = Field(default=200, ge=1, le=1000)


class SearchPage(Record):
    items: list[ImageRecord]
    next_cursor: str | None = None
    total: int | None = None
    """Given on the first page when counting is cheap; None otherwise."""
    random_seed: int | None = None


class FacetValue(Record):
    value: str
    count: int


class Facets(Record):
    platforms: list[FacetValue] = Field(default_factory=list)
    models: list[FacetValue] = Field(default_factory=list)
    samplers: list[FacetValue] = Field(default_factory=list)
    sizes: list[FacetValue] = Field(default_factory=list)
    total: int = 0


class DayCount(Record):
    day: str
    count: int


class Stats(Record):
    total: int
    per_day: list[DayCount]
    per_month: list[DayCount]
    platforms: list[FacetValue]
    models: list[FacetValue]
    samplers: list[FacetValue]
    loras: list[FacetValue]


class ScanRequest(Record):
    root_id: str | None = None
    path: str | None = None
    full: bool = False
    """Re-read every file, ignoring folder and file modification times."""
    reparse: bool = False
    """Re-run the parsers over the stored chunks without reading the files again."""


class RootScanState(Record):
    root_id: str
    state: Literal["idle", "queued", "scanning", "failed"] = "idle"
    full: bool = False
    folders_seen: int = 0
    files_seen: int = 0
    files_indexed: int = 0
    files_failed: int = 0
    current: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    error: str | None = None


class ScanStatus(Record):
    running: bool
    queued: int
    """Jobs waiting, on-demand indexing included."""
    roots: list[RootScanState]


class RootIndexSummary(Record):
    root_id: str
    images: int
    missing: int
    failed: int
    last_scan: datetime | None = None
