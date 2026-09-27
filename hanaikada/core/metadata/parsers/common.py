"""Value conversions shared by the parsers. Every one is lenient: bad input gives ``None``."""

import math
import re
from typing import Any

from hanaikada.core.metadata.models import ExtraValue, HashKind

_HEX = re.compile(r"^(?:0x)?([0-9a-fA-F]+)$")


def to_int(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value) if math.isfinite(value) else None
    if isinstance(value, str):
        text = value.strip()
        try:
            return int(text)
        except ValueError:
            number = to_float(text)
            return int(number) if number is not None and float(number).is_integer() else None
    return None


def to_float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        number = float(value)
        return number if math.isfinite(number) else None
    if isinstance(value, str):
        try:
            number = float(value.strip())
        except ValueError:
            return None
        return number if math.isfinite(number) else None
    return None


def to_str(value: Any) -> str | None:
    if isinstance(value, str):
        return value if value.strip() else None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return str(value)
    return None


def to_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return {"true": True, "false": False}.get(value.strip().lower())
    return None


def file_stem(path: str) -> str:
    """``"sdxl/style/foo.safetensors"`` → ``"foo"``. Folder separators of either kind are dropped."""
    name = path.replace("\\", "/").rsplit("/", 1)[-1]
    stem, dot, ext = name.rpartition(".")
    if dot and stem and 1 <= len(ext) <= 12 and " " not in ext:
        return stem
    return name


def hash_kind(value: str | None) -> HashKind | None:
    if not value:
        return None
    if value.lower().startswith("blake3:"):
        return "blake3"
    match = _HEX.match(value.strip())
    if not match:
        return "unknown"
    kinds: dict[int, HashKind] = {10: "sha256-10", 12: "sha256-12"}
    return kinds.get(len(match.group(1)), "unknown")


def extra_value(value: Any, max_length: int = 2000) -> ExtraValue:
    """A value fit for ``GenerationInfo.extras``: scalars as they are, anything else as short text."""
    if value is None or isinstance(value, (bool, int, float)):
        if isinstance(value, float) and not math.isfinite(value):
            return str(value)
        return value
    if isinstance(value, str):
        return value if len(value) <= max_length else value[:max_length] + "…"
    import json

    try:
        text = json.dumps(value, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        text = str(value)
    return text if len(text) <= max_length else text[:max_length] + "…"


def dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out
