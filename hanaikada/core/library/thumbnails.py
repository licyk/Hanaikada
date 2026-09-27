"""Resized images, cached in the data directory.

An image browser asks for thousands of thumbnails a session, so they are cheap to hit: the cache
key covers the path, the size and the file's size and mtime (a changed file gets a new key), the
key doubles as the ETag, and the URL carries the mtime so responses can be cached for a year.
Generation is bounded — a few at a time, one per key — so opening a folder of 500 new images does
not start 500 decoders.
"""

import hashlib
import logging
import os
import threading
from dataclasses import dataclass
from pathlib import Path

from hanaikada.core.imaging import Image, ImageOps

logger = logging.getLogger(__name__)

ALLOWED_SIZES = (128, 256, 384, 512, 768)
# Above this many pixels a PNG is decoded once, at the largest size, and smaller sizes derive from that.
LARGE_IMAGE_PIXELS = 16_000_000
_LOCK_STRIPES = 64


def nearest_size(size: int) -> int:
    return next((s for s in ALLOWED_SIZES if s >= size), ALLOWED_SIZES[-1])


@dataclass(frozen=True)
class Thumbnail:
    path: Path
    etag: str
    media_type: str = "image/webp"


class ThumbnailService:
    def __init__(self, cache_dir: Path, quality: int = 82, workers: int | None = None) -> None:
        self.cache_dir = cache_dir
        self.quality = quality
        count = workers if workers is not None else max(2, min(4, (os.cpu_count() or 2) // 2))
        self._semaphore = threading.BoundedSemaphore(count)
        self._locks = [threading.Lock() for _ in range(_LOCK_STRIPES)]

    def key(self, source: Path, size: int, st: os.stat_result | None = None) -> str:
        st = st or source.stat()
        return hashlib.sha1(f"{source}|{nearest_size(size)}|{st.st_mtime_ns}|{st.st_size}|{self.quality}".encode()).hexdigest()

    def cache_path(self, key: str) -> Path:
        return self.cache_dir / key[:2] / f"{key}.webp"

    def get(self, source: Path, size: int, seed: Path | None = None) -> Thumbnail:
        """A cached WebP of ``source`` no larger than ``size`` on its longer side.

        ``seed`` is a ready-made smaller image of the same picture (InvokeAI's own thumbnail); it
        is resized instead of decoding the source when it is at least as large as asked.
        """
        size = nearest_size(size)
        st = source.stat()
        key = self.key(source, size, st)
        target = self.cache_path(key)
        if target.exists():
            return Thumbnail(target, key)
        with self._locks[int(key[:4], 16) % _LOCK_STRIPES]:
            if target.exists():
                return Thumbnail(target, key)
            with self._semaphore:
                self._generate(source, size, target, st, seed)
        return Thumbnail(target, key)

    def _generate(self, source: Path, size: int, target: Path, st: os.stat_result, seed: Path | None) -> None:
        target.parent.mkdir(parents=True, exist_ok=True)
        origin = source
        if seed is not None and seed.is_file():
            try:
                with Image.open(seed) as probe:
                    if max(probe.size) >= size:
                        origin = seed
            except OSError:
                pass
        if origin is source and size < ALLOWED_SIZES[-1] and source.suffix.lower() == ".png":
            with Image.open(source) as probe:
                large = probe.size[0] * probe.size[1] > LARGE_IMAGE_PIXELS
            if large:
                largest = self.cache_path(self.key(source, ALLOWED_SIZES[-1], st))
                if not largest.exists():
                    self._write(source, ALLOWED_SIZES[-1], largest)
                origin = largest
        self._write(origin, size, target)

    def _write(self, origin: Path, size: int, target: Path) -> None:
        with Image.open(origin) as img:
            if img.format == "JPEG":
                img.draft("RGB", (size, size))
            img = ImageOps.exif_transpose(img)
            # The shorter side gets ``size``, so a square grid cell cropping the image stays sharp.
            img.thumbnail((size * 2, size) if img.width >= img.height else (size, size * 2))
            if img.mode not in ("RGB", "RGBA"):
                img = img.convert("RGBA" if "A" in img.getbands() or img.mode == "P" else "RGB")
            target.parent.mkdir(parents=True, exist_ok=True)
            tmp = target.with_name(f"{target.stem}.{threading.get_ident()}.tmp")
            img.save(tmp, "WEBP", quality=self.quality, method=4)
        os.replace(tmp, target)

    def forget(self, source: Path, st: os.stat_result) -> int:
        """Remove every cached size of a file. ``st`` is its stat from before it was moved or deleted."""
        removed = 0
        for size in ALLOWED_SIZES:
            path = self.cache_path(self.key(source, size, st))
            try:
                path.unlink()
                removed += 1
            except FileNotFoundError:
                pass
        return removed

    def clear(self) -> int:
        removed = 0
        for path in self.cache_dir.glob("*/*.webp"):
            try:
                path.unlink()
                removed += 1
            except OSError:
                pass
        return removed

    def usage(self) -> tuple[int, int]:
        """``(files, bytes)`` in the cache."""
        files = size = 0
        for path in self.cache_dir.glob("*/*.webp"):
            try:
                size += path.stat().st_size
                files += 1
            except OSError:
                pass
        return files, size

    def sweep(self, max_bytes: int) -> int:
        """Delete the least recently written entries until the cache fits. Returns the number removed."""
        entries: list[tuple[float, int, Path]] = []
        total = 0
        for path in self.cache_dir.glob("*/*"):
            try:
                st = path.stat()
            except OSError:
                continue
            if path.suffix == ".tmp":
                path.unlink(missing_ok=True)
                continue
            entries.append((st.st_mtime, st.st_size, path))
            total += st.st_size
        removed = 0
        if total <= max_bytes:
            return 0
        for _mtime, size, path in sorted(entries):
            if total <= max_bytes:
                break
            try:
                path.unlink()
            except OSError:
                continue
            total -= size
            removed += 1
        logger.info("Thumbnail cache swept: %d files removed", removed)
        return removed
