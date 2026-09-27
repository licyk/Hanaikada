"""What a client sees of a parse: the normalised record and every raw entry, in one shape.

``hanaikada info --json`` and ``POST /images/parse`` both return a ParseResult.
"""

from pydantic import Field

from hanaikada.core.metadata.models import GenerationInfo, ParsedImage, RawMetadata
from hanaikada.core.record import Record


class RawChunk(Record):
    key: str
    value: str
    source: str | None = None
    truncated: bool = False


class RawView(Record):
    """Everything readable in the file: text chunks, and the other container and EXIF entries."""

    format: str | None = None
    width: int | None = None
    height: int | None = None
    mode: str | None = None
    frames: int = 1
    chunks: list[RawChunk] = Field(default_factory=list)
    info: dict[str, str] = Field(default_factory=dict)
    sidecars: list[str] = Field(default_factory=list)


class ParseResult(Record):
    info: GenerationInfo
    raw: RawView
    error: str | None = None


def raw_view(raw: RawMetadata, truncated: set[str] | None = None) -> RawView:
    return RawView(
        format=raw.format,
        width=raw.width,
        height=raw.height,
        mode=raw.mode,
        frames=raw.frames,
        chunks=[RawChunk(key=k, value=v, source=raw.chunk_sources.get(k), truncated=k in (truncated or set())) for k, v in raw.chunks.items()],
        info=raw.info,
        sidecars=raw.sidecars,
    )


def parse_result(parsed: ParsedImage) -> ParseResult:
    return ParseResult(info=parsed.info, raw=raw_view(parsed.raw), error=parsed.error)
