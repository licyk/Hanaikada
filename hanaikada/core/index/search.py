"""Turn a SearchQuery into SQL: filters, full-text, tags, keyset paging.

Tag clauses are IIB's: all-of is ``HAVING COUNT(DISTINCT tag_id) = N``, any-of an ``IN``, none-of a
``NOT IN``. Text goes through ``images_fts`` (trigram: case-insensitive substrings) with the text
quoted as one phrase so punctuation in prompts is literal, or through ``LIKE`` when FTS is not
available or the text is shorter than a trigram. The cursor is a keyset over ``(sort value, id)``
taken from the last row *read*, so a run of rows filtered out afterwards does not rewind a page.
"""

import base64
import json
import re
from datetime import datetime, timedelta
from typing import Any

from hanaikada.core.errors import ValidationError
from hanaikada.core.index.models import SearchQuery
from hanaikada.core.index.records import seed_to_db

TEXT_COLUMNS = {"prompt": "prompt", "negative": "negative_prompt", "name": "name", "model": "model_name", "loras": "loras"}
# Keys that never collide with real values, so NULLs sort to one end and the keyset stays total.
SORT_KEYS = {
    "mtime": "mtime_ns",
    "ctime": "COALESCE(ctime_ns, mtime_ns)",
    "name": "name",
    "size": "size",
    "seed": "COALESCE(seed, -9223372036854775808)",
    "random": "(((id + :random_seed) * 2654435761) % 4294967291)",
}
REGEX_SCAN_CAP = 20_000
REGEX_BATCH = 500


def _like_escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def fts_phrase(text: str, columns: list[str] | None = None) -> str:
    """One quoted FTS5 phrase, optionally limited to some columns."""
    phrase = '"' + text.replace('"', '""') + '"'
    if columns:
        return "{" + " ".join(columns) + "}: " + phrase
    return phrase


def _parse_date(value: str, end: bool) -> int:
    """An ISO date or date-time → nanoseconds. A date alone covers the whole day at either end."""
    try:
        # A naive value is local time, as the user reads dates in the interface.
        moment = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise ValidationError(f"Not a date: {value!r}") from None
    if len(value) == 10 and end:
        moment += timedelta(days=1)
    return int(moment.timestamp()) * 1_000_000_000 + moment.microsecond * 1000


def build_where(q: SearchQuery, fts: bool) -> tuple[list[str], dict[str, Any]]:
    """The WHERE clauses and named parameters for every filter except the cursor."""
    clauses: list[str] = []
    params: dict[str, Any] = {}
    counter = iter(range(10_000))

    def bind(value: Any) -> str:
        name = f"p{next(counter)}"
        params[name] = value
        return f":{name}"

    def bind_list(values: list[Any]) -> str:
        return ", ".join(bind(v) for v in values)

    if not q.include_missing:
        clauses.append("missing_since IS NULL")
    if q.root_ids:
        clauses.append(f"root_id IN ({bind_list(q.root_ids)})")
    if q.path_prefix:
        prefix = q.path_prefix.strip("/")
        if prefix:
            clauses.append(f"(dir = {bind(prefix)} OR dir LIKE {bind(_like_escape(prefix) + '/%')} ESCAPE '\\')")
    if q.platforms:
        clauses.append(f"platform IN ({bind_list(q.platforms)})")
    if q.models:
        clauses.append(f"model_name IN ({bind_list(q.models)})")
    if q.samplers:
        values = bind_list(q.samplers)
        clauses.append(f"(sampler_norm IN ({values}) OR sampler IN ({values}))")
    if q.seed is not None:
        clauses.append(f"seed = {bind(seed_to_db(q.seed))}")
    for column, bounds in (("steps", q.steps), ("cfg_scale", q.cfg)):
        if bounds is not None:
            low, high = bounds
            if low is not None:
                clauses.append(f"{column} >= {bind(low)}")
            if high is not None:
                clauses.append(f"{column} <= {bind(high)}")
    if q.width is not None:
        clauses.append(f"width = {bind(q.width)}")
    if q.height is not None:
        clauses.append(f"height = {bind(q.height)}")
    if q.orientation == "portrait":
        clauses.append("height > width")
    elif q.orientation == "landscape":
        clauses.append("width > height")
    elif q.orientation == "square":
        clauses.append("width = height")
    if q.date is not None:
        start, end = q.date
        if start:
            clauses.append(f"mtime_ns >= {bind(_parse_date(start, end=False))}")
        if end:
            clauses.append(f"mtime_ns < {bind(_parse_date(end, end=True))}")
    if q.all_tags:
        tags = sorted(set(q.all_tags))
        clauses.append(f"id IN (SELECT image_id FROM image_tags WHERE tag_id IN ({bind_list(tags)}) GROUP BY image_id HAVING COUNT(DISTINCT tag_id) = {len(tags)})")
    if q.any_tags:
        clauses.append(f"id IN (SELECT image_id FROM image_tags WHERE tag_id IN ({bind_list(sorted(set(q.any_tags)))}))")
    if q.not_tags:
        clauses.append(f"id NOT IN (SELECT image_id FROM image_tags WHERE tag_id IN ({bind_list(sorted(set(q.not_tags)))}))")
    text = (q.text or "").strip()
    if text:
        fields = q.text_in or list(TEXT_COLUMNS)
        columns = [TEXT_COLUMNS[f] for f in fields]
        if fts and len(text) >= 3:
            clauses.append(f"id IN (SELECT rowid FROM images_fts WHERE images_fts MATCH {bind(fts_phrase(text, columns if len(columns) < len(TEXT_COLUMNS) else None))})")
        else:
            pattern = bind("%" + _like_escape(text) + "%")
            clauses.append("(" + " OR ".join(f"{c} LIKE {pattern} ESCAPE '\\'" for c in columns) + ")")
    return clauses, params


def encode_cursor(sort: str, descending: bool, value: Any, row_id: int) -> str:
    raw = json.dumps([sort, descending, value, row_id], separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def decode_cursor(cursor: str, sort: str, descending: bool) -> tuple[Any, int]:
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        stored_sort, stored_desc, value, row_id = json.loads(base64.urlsafe_b64decode(padded))
    except (ValueError, TypeError):
        raise ValidationError("Invalid cursor") from None
    if stored_sort != sort or stored_desc != descending or not isinstance(row_id, int):
        raise ValidationError("The cursor belongs to a different sort order")
    return value, row_id


def order_and_keyset(q: SearchQuery, params: dict[str, Any]) -> tuple[str, str, str | None]:
    """``(key expression, ORDER BY, keyset clause or None)``."""
    key = SORT_KEYS[q.sort]
    if q.sort == "random":
        params["random_seed"] = q.random_seed or 0
    direction = "DESC" if q.descending else "ASC"
    order = f"{key} {direction}, id {direction}"
    keyset = None
    if q.cursor:
        value, row_id = decode_cursor(q.cursor, q.sort, q.descending)
        params["cursor_value"] = value
        params["cursor_id"] = row_id
        op = "<" if q.descending else ">"
        keyset = f"({key} {op} :cursor_value OR ({key} = :cursor_value AND id {op} :cursor_id))"
    return key, order, keyset


def compile_regex(pattern: str) -> re.Pattern[str]:
    try:
        return re.compile(pattern, re.IGNORECASE)
    except re.error as e:
        raise ValidationError(f"Invalid regular expression: {e}") from None
