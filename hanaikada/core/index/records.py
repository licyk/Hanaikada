"""SQL for image rows, their raw text, their tags, and scanned folders.

Every function takes an open connection so a caller can batch many files into one transaction.
"""

import json
import sqlite3
from collections.abc import Iterable
from datetime import datetime, timezone
from typing import Any

from hanaikada.core.index.models import PROMPT_EXCERPT, ImageRecord, Tag
from hanaikada.core.index.tags import DerivedTag
from hanaikada.core.metadata.models import ParsedImage

AUTO_TAG_TYPES = ("prompt", "lora", "model", "sampler", "platform", "size")
MANUAL_TAG_TYPES = ("custom", "board")
_INT64_MAX = 2**63 - 1

LISTING_COLUMNS = (
    "id, root_id, rel_path, name, ext, size, mtime_ns, ctime_ns, width, height, format, platform, substr(prompt, 1, 400) AS prompt, "
    "seed, steps, cfg_scale, sampler, sampler_norm, model_name, gen_width, gen_height, mode, parse_error IS NOT NULL AS has_error, missing_since"
)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def seed_to_db(seed: int | None) -> int | None:
    """SQLite integers are signed 64-bit; ComfyUI seeds reach 2**64 - 1. Stored two's complement."""
    if seed is None:
        return None
    if seed > _INT64_MAX:
        return seed - 2**64 if seed < 2**64 else None
    return seed if seed >= -(2**63) else None


def seed_from_db(value: int | None) -> int | None:
    if value is None:
        return None
    return value + 2**64 if value < 0 else value


def mtime_dt(ns: int) -> datetime:
    return datetime.fromtimestamp(ns / 1e9, tz=timezone.utc)


def record_from_row(row: sqlite3.Row, tag_ids: list[int] | None = None, blur: bool = False) -> ImageRecord:
    prompt = row["prompt"]
    if prompt is not None and len(prompt) > PROMPT_EXCERPT:
        prompt = prompt[:PROMPT_EXCERPT]
    return ImageRecord(
        id=row["id"],
        root_id=row["root_id"],
        path=row["rel_path"],
        name=row["name"],
        ext=row["ext"],
        size=row["size"],
        mtime=mtime_dt(row["mtime_ns"]),
        version=str(row["mtime_ns"]),
        width=row["width"],
        height=row["height"],
        format=row["format"],
        platform=row["platform"],
        prompt=prompt,
        seed=seed_from_db(row["seed"]),
        steps=row["steps"],
        cfg_scale=row["cfg_scale"],
        sampler=row["sampler"],
        sampler_norm=row["sampler_norm"],
        model_name=row["model_name"],
        gen_width=row["gen_width"],
        gen_height=row["gen_height"],
        mode=row["mode"],
        has_error=bool(row["has_error"]),
        missing=row["missing_since"] is not None,
        tag_ids=tag_ids or [],
        blur=blur,
    )


def tag_from_row(row: sqlite3.Row) -> Tag:
    return Tag(id=row["id"], name=row["name"], type=row["type"], color=row["color"], count=row["count"])


def image_values(root_id: str, rel_path: str, size: int, mtime_ns: int, ctime_ns: int | None, parsed: ParsedImage) -> dict[str, Any]:
    info, raw = parsed.info, parsed.raw
    name = rel_path.rsplit("/", 1)[-1]
    ext = ("." + name.rsplit(".", 1)[1].lower()) if "." in name else ""
    return {
        "root_id": root_id,
        "rel_path": rel_path,
        "dir": rel_path.rsplit("/", 1)[0] if "/" in rel_path else "",
        "name": name,
        "ext": ext,
        "size": size,
        "mtime_ns": mtime_ns,
        "ctime_ns": ctime_ns,
        "width": raw.width,
        "height": raw.height,
        "format": raw.format,
        "platform": info.platform,
        "platform_version": info.platform_version,
        "family": info.family,
        "prompt": info.prompt,
        "negative_prompt": info.negative_prompt,
        "seed": seed_to_db(info.seed),
        "steps": info.steps,
        "cfg_scale": info.cfg_scale,
        "distilled_cfg": info.distilled_cfg,
        "sampler": info.sampler,
        "sampler_norm": info.sampler_norm,
        "scheduler": info.scheduler,
        "denoise": info.denoise,
        "clip_skip": info.clip_skip,
        "model_name": info.model.name if info.model else None,
        "model_hash": info.model.hash if info.model else None,
        "vae_name": info.vae.name if info.vae else None,
        "loras": " ".join(lora.name for lora in info.loras) or None,
        "gen_width": info.width,
        "gen_height": info.height,
        "mode": info.mode,
        "info": info.model_dump_json(),
        "parse_error": parsed.error,
        "indexed_at": now_iso(),
        "missing_since": None,
    }


def upsert_image(conn: sqlite3.Connection, values: dict[str, Any]) -> tuple[int, bool]:
    """Insert or update one row by ``(root_id, rel_path)``. Returns ``(id, created)``."""
    existing = conn.execute("SELECT id FROM images WHERE root_id = ? AND rel_path = ?", (values["root_id"], values["rel_path"])).fetchone()
    columns = list(values)
    if existing is None:
        cursor = conn.execute(f"INSERT INTO images({', '.join(columns)}) VALUES ({', '.join('?' for _ in columns)})", [values[c] for c in columns])
        return int(cursor.lastrowid or 0), True
    updates = [c for c in columns if c not in ("root_id", "rel_path")]
    conn.execute(f"UPDATE images SET {', '.join(f'{c} = ?' for c in updates)} WHERE id = ?", [*(values[c] for c in updates), existing["id"]])
    return int(existing["id"]), False


def replace_text(conn: sqlite3.Connection, image_id: int, parsed: ParsedImage, max_bytes: int) -> None:
    conn.execute("DELETE FROM image_text WHERE image_id = ?", (image_id,))
    rows = []
    for key, value in parsed.raw.chunks.items():
        truncated = len(value.encode("utf-8", errors="replace")) > max_bytes
        if truncated:
            value = value.encode("utf-8", errors="replace")[:max_bytes].decode("utf-8", errors="ignore")
        rows.append((image_id, key, value, parsed.raw.chunk_sources.get(key), int(truncated)))
    conn.executemany("INSERT INTO image_text(image_id, key, value, source, truncated) VALUES (?, ?, ?, ?, ?)", rows)


class TagCache:
    """Tag ids by ``(name, type)``, so a scan does not look each one up again."""

    def __init__(self) -> None:
        self._ids: dict[tuple[str, str], int] = {}

    def clear(self) -> None:
        self._ids.clear()

    def ensure(self, conn: sqlite3.Connection, name: str, tag_type: str) -> int:
        key = (name, tag_type)
        cached = self._ids.get(key)
        if cached is not None:
            return cached
        row = conn.execute("SELECT id FROM tags WHERE name = ? AND type = ?", key).fetchone()
        if row is None:
            tag_id = int(conn.execute("INSERT INTO tags(name, type) VALUES (?, ?)", key).lastrowid or 0)
        else:
            tag_id = int(row["id"])
        self._ids[key] = tag_id
        return tag_id

    def forget(self, tag_id: int) -> None:
        for key, value in list(self._ids.items()):
            if value == tag_id:
                del self._ids[key]


def set_auto_tags(conn: sqlite3.Connection, cache: TagCache, image_id: int, tags: Iterable[DerivedTag]) -> None:
    """Make an image's automatic tags exactly ``tags``; custom and board tags are left alone."""
    wanted = {cache.ensure(conn, t.name, t.type) for t in tags}
    current = {
        row["tag_id"]
        for row in conn.execute(
            f"SELECT it.tag_id FROM image_tags it JOIN tags t ON t.id = it.tag_id WHERE it.image_id = ? AND t.type IN ({', '.join('?' for _ in AUTO_TAG_TYPES)})",
            (image_id, *AUTO_TAG_TYPES),
        )
    }
    stale = current - wanted
    if stale:
        conn.executemany("DELETE FROM image_tags WHERE image_id = ? AND tag_id = ?", [(image_id, t) for t in stale])
    added = wanted - current
    if added:
        stamp = now_iso()
        conn.executemany("INSERT OR IGNORE INTO image_tags(image_id, tag_id, created_at) VALUES (?, ?, ?)", [(image_id, t, stamp) for t in added])


def delete_empty_auto_tags(conn: sqlite3.Connection) -> None:
    conn.execute(f"DELETE FROM tags WHERE count <= 0 AND type IN ({', '.join('?' for _ in AUTO_TAG_TYPES)})", AUTO_TAG_TYPES)


def manual_tag_ids(conn: sqlite3.Connection, image_ids: list[int]) -> dict[int, list[int]]:
    """Custom and board tag ids per image, for the dots on grid cells."""
    out: dict[int, list[int]] = {i: [] for i in image_ids}
    for start in range(0, len(image_ids), 500):
        chunk = image_ids[start : start + 500]
        rows = conn.execute(
            f"SELECT it.image_id, it.tag_id FROM image_tags it JOIN tags t ON t.id = it.tag_id "
            f"WHERE it.image_id IN ({', '.join('?' for _ in chunk)}) AND t.type IN ('custom', 'board') ORDER BY it.created_at",
            chunk,
        )
        for row in rows:
            out[row["image_id"]].append(row["tag_id"])
    return out


def images_with_tags(conn: sqlite3.Connection, image_ids: list[int], tag_ids: set[int]) -> set[int]:
    if not image_ids or not tag_ids:
        return set()
    found: set[int] = set()
    tags = sorted(tag_ids)
    for start in range(0, len(image_ids), 500):
        chunk = image_ids[start : start + 500]
        rows = conn.execute(
            f"SELECT DISTINCT image_id FROM image_tags WHERE image_id IN ({', '.join('?' for _ in chunk)}) AND tag_id IN ({', '.join('?' for _ in tags)})",
            [*chunk, *tags],
        )
        found.update(row["image_id"] for row in rows)
    return found


def upsert_folder(conn: sqlite3.Connection, root_id: str, rel_path: str, mtime_ns: int) -> None:
    parent = None if rel_path == "" else (rel_path.rsplit("/", 1)[0] if "/" in rel_path else "")
    conn.execute(
        "INSERT INTO folders(root_id, rel_path, parent, mtime_ns, scanned_at) VALUES (?, ?, ?, ?, ?) "
        "ON CONFLICT(root_id, rel_path) DO UPDATE SET mtime_ns = excluded.mtime_ns, scanned_at = excluded.scanned_at",
        (root_id, rel_path, parent, mtime_ns, now_iso()),
    )


def info_json(row: sqlite3.Row) -> dict[str, Any]:
    try:
        data = json.loads(row["info"])
    except (TypeError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}
