"""Builders for synthetic test images: PNG chunks, EXIF UserComments, GIF comments."""

import io
import json
import struct
import zlib
from pathlib import Path
from typing import Any

from PIL import Image

FIXTURES = Path(__file__).parent / "fixtures" / "metadata"


def chunk(ctype: bytes, data: bytes) -> bytes:
    return struct.pack(">I", len(data)) + ctype + data + struct.pack(">I", zlib.crc32(ctype + data) & 0xFFFFFFFF)


def text_chunk(key: str, value: str, kind: str = "tEXt") -> bytes:
    if kind == "tEXt":
        return chunk(b"tEXt", key.encode("latin-1") + b"\x00" + value.encode("latin-1"))
    if kind == "zTXt":
        return chunk(b"zTXt", key.encode("latin-1") + b"\x00\x00" + zlib.compress(value.encode("latin-1")))
    if kind == "iTXt":
        return chunk(b"iTXt", key.encode("latin-1") + b"\x00\x00\x00\x00\x00" + value.encode("utf-8"))
    if kind == "iTXt-z":
        return chunk(b"iTXt", key.encode("latin-1") + b"\x00\x01\x00\x00\x00" + zlib.compress(value.encode("utf-8")))
    if kind == "comf":
        return chunk(b"comf", key.encode("latin-1") + b"\x00" + value.encode("utf-8"))
    raise ValueError(kind)


def png_bytes(chunks: list[bytes] | None = None, size: tuple[int, int] = (2, 3), after_idat: list[bytes] | None = None, mode: str = "RGB") -> bytes:
    """A small PNG with ``chunks`` after IHDR and ``after_idat`` before IEND."""
    buffer = io.BytesIO()
    Image.new(mode, size, (200, 100, 50) if mode == "RGB" else None).save(buffer, "PNG")
    data = buffer.getvalue()
    head, tail = data[:33], data[33:]
    iend = tail.rindex(b"IEND") - 4
    return head + b"".join(chunks or []) + tail[:iend] + b"".join(after_idat or []) + tail[iend:]


def write_png(path: Path, texts: dict[str, str] | None = None, kind: str = "tEXt", size: tuple[int, int] = (2, 3)) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(png_bytes([text_chunk(k, v, kind) for k, v in (texts or {}).items()], size=size))
    return path


def user_comment_exif(text: str, encoding: str = "unicode") -> bytes:
    import piexif
    import piexif.helper

    return piexif.dump({"Exif": {piexif.ExifIFD.UserComment: piexif.helper.UserComment.dump(text, encoding=encoding)}})


def write_jpeg(path: Path, text: str | None = None, encoding: str = "unicode", size: tuple[int, int] = (4, 2), exif: bytes | None = None) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    kwargs: dict[str, Any] = {}
    if exif is not None:
        kwargs["exif"] = exif
    elif text is not None:
        kwargs["exif"] = user_comment_exif(text, encoding)
    Image.new("RGB", size, (10, 20, 30)).save(path, "JPEG", **kwargs)
    return path


def comfy_webp_exif(prompt: dict[str, Any], workflow: dict[str, Any] | None = None) -> bytes:
    """EXIF as ComfyUI's WebP and AVIF writers make it: IFD0 Model = "prompt:<json>", Make = "workflow:<json>"."""
    import piexif

    zeroth: dict[int, bytes] = {piexif.ImageIFD.Model: ("prompt:" + json.dumps(prompt)).encode()}
    if workflow is not None:
        zeroth[piexif.ImageIFD.Make] = ("workflow:" + json.dumps(workflow)).encode()
    return piexif.dump({"0th": zeroth})


INFOTEXT = (
    "1girl, solo, <lora:styleA:0.8>, (masterpiece:1.2)\n"
    "cherry blossoms, BREAK outdoors\n"
    "Negative prompt: lowres, bad anatomy\n"
    "Steps: 28, Sampler: DPM++ 2M, Schedule type: Karras, CFG scale: 6.5, Seed: 1234567890, Size: 832x1216, Model hash: 0123456789, Model: animeModel_v1, "
    'Lora hashes: "styleA: 0123456789ab", Version: v1.10.1'
)
