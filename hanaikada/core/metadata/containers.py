"""Read every text slot of an image file, before any platform logic.

PNG is read by a small chunk walker rather than Pillow: Pillow only fills ``image.info`` from the
chunks before the pixel data, and reaching the ones after it (an APNG's ``comf`` chunks, text a
tool appended at the end) would mean decoding the whole image. The walker seeks past ``IDAT``
instead. Every other format is opened lazily with Pillow, which reads the header only, and its
EXIF block is parsed with ``piexif``, falling back to a manual IFD walk for blocks piexif rejects.
"""

import io
import logging
import re
import struct
import zlib
from pathlib import Path
from typing import Any, BinaryIO

from PIL import Image

from hanaikada.core.errors import UnsupportedFileError
from hanaikada.core.metadata.models import RawMetadata

logger = logging.getLogger(__name__)

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
# A decompressed text chunk larger than this is cut off: a zip bomb must not exhaust memory.
MAX_TEXT_BYTES = 64 * 1024 * 1024
MAX_SIDECAR_BYTES = 1024 * 1024
MAX_INFO_VALUE = 2000

# Keys that carry generation data. A file holding none of them may have a ``.txt`` sidecar.
GENERATION_KEYS = {
    "parameters",
    "postprocessing",
    "prompt",
    "workflow",
    "invokeai_metadata",
    "invokeai_graph",
    "invokeai_workflow",
    "invokeai",
    "sd-metadata",
    "dream",
    "Dream",
    "UserComment",
    "comment",
    "Comment",
}
XMP_KEYS = {"XML:com.adobe.xmp", "xmp"}

EXIF_ORIENTATION = 0x0112
EXIF_USER_COMMENT = 0x9286
EXIF_IFD_POINTER = 0x8769
_TIFF_TYPE_SIZES = {1: 1, 2: 1, 3: 2, 4: 4, 5: 8, 6: 1, 7: 1, 8: 2, 9: 4, 10: 8, 11: 4, 12: 8}
_KEY_JSON = re.compile(r"^([A-Za-z_][\w\- ]{0,63}):\s*([\[{].*)$", re.DOTALL)


def decode_text(data: bytes) -> str:
    """PNG ``tEXt`` is Latin-1 by the specification, but many writers put UTF-8 there."""
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return data.decode("latin-1")


def _inflate(data: bytes) -> bytes:
    d = zlib.decompressobj()
    out = d.decompress(data, MAX_TEXT_BYTES)
    if d.unconsumed_tail:
        logger.debug("Text chunk larger than %d bytes truncated", MAX_TEXT_BYTES)
    return out


def decode_user_comment(data: bytes) -> str:
    """Decode an EXIF ``UserComment``: an 8-byte charset prefix, then the text.

    The WebUI writes ``UNICODE\\0`` followed by UTF-16 big-endian. Some writers use little-endian
    under the same prefix; the position of the zero bytes tells them apart for Latin text.
    """
    prefix, body = data[:8], data[8:]
    if prefix == b"UNICODE\x00":
        encoding = "utf-16-be"
        if len(body) >= 2 and body[1] == 0 and body[0] != 0:
            encoding = "utf-16-le"
        text = body.decode(encoding, errors="replace")
    elif prefix == b"ASCII\x00\x00\x00":
        text = body.decode("utf-8", errors="replace")
    elif prefix == b"JIS\x00\x00\x00\x00\x00":
        text = body.decode("shift_jis", errors="replace")
    elif prefix == b"\x00" * 8:
        text = body.decode("utf-8", errors="replace")
    else:
        text = data.decode("utf-8", errors="ignore")
    return text.strip("\x00")


# -- EXIF ------------------------------------------------------------------------------------------


def _manual_ifds(data: bytes) -> dict[str, dict[int, Any]]:
    """Walk IFD0 and the Exif IFD of a TIFF block by hand. Values are bytes, ints or tuples."""
    if data.startswith(b"Exif\x00\x00"):
        data = data[6:]
    if data[:2] == b"II":
        endian = "<"
    elif data[:2] == b"MM":
        endian = ">"
    else:
        raise ValueError("Not a TIFF block")

    def read_ifd(offset: int) -> dict[int, Any]:
        entries: dict[int, Any] = {}
        if offset <= 0 or offset + 2 > len(data):
            return entries
        (count,) = struct.unpack_from(endian + "H", data, offset)
        for i in range(min(count, 1000)):
            pos = offset + 2 + i * 12
            if pos + 12 > len(data):
                break
            tag, typ, n = struct.unpack_from(endian + "HHI", data, pos)
            size = _TIFF_TYPE_SIZES.get(typ, 1) * n
            start = pos + 8 if size <= 4 else struct.unpack_from(endian + "I", data, pos + 8)[0]
            raw = data[start : start + size]
            if typ in (2, 7, 1, 6):
                entries[tag] = raw
            elif typ == 3 and n >= 1 and len(raw) >= 2:
                entries[tag] = struct.unpack_from(endian + "H", raw)[0]
            elif typ == 4 and n >= 1 and len(raw) >= 4:
                entries[tag] = struct.unpack_from(endian + "I", raw)[0]
            else:
                entries[tag] = raw
        return entries

    (first,) = struct.unpack_from(endian + "I", data, 4)
    ifd0 = read_ifd(first)
    exif_ptr = ifd0.get(EXIF_IFD_POINTER)
    exif = read_ifd(exif_ptr) if isinstance(exif_ptr, int) else {}
    return {"0th": ifd0, "Exif": exif}


def load_exif(data: bytes) -> dict[str, dict[int, Any]]:
    """Parse an EXIF block into ``{"0th": {...}, "Exif": {...}, ...}``: piexif, else by hand."""
    try:
        import piexif

        exif = piexif.load(data if data[:4] in (b"Exif", b"II*\x00", b"MM\x00*") else b"Exif\x00\x00" + data)
        return {k: v for k, v in exif.items() if isinstance(v, dict)}
    except Exception as e:  # noqa: BLE001 - piexif raises many types on malformed blocks
        logger.debug("piexif rejected an EXIF block (%s); walking it by hand", e)
    try:
        return _manual_ifds(data)
    except (ValueError, struct.error) as e:
        logger.debug("Unreadable EXIF block: %s", e)
        return {}


def _tag_name(ifd: str, tag: int) -> str:
    try:
        import piexif

        return str(piexif.TAGS[ifd][tag]["name"])
    except Exception:  # noqa: BLE001
        return f"0x{tag:04x}"


def _display(value: Any) -> str:
    if isinstance(value, bytes):
        text = value.decode("utf-8", errors="replace").strip("\x00")
    elif isinstance(value, tuple) and len(value) == 2 and all(isinstance(v, int) for v in value) and value[1]:
        text = f"{value[0] / value[1]:g}"
    else:
        text = str(value)
    return text if len(text) <= MAX_INFO_VALUE else text[:MAX_INFO_VALUE] + "…"


def apply_exif(raw: RawMetadata, data: bytes, source: str = "exif") -> int | None:
    """Put an EXIF block's generation text into ``raw.chunks`` and the rest into ``raw.info``.

    Returns the orientation tag, if any.
    """
    ifds = load_exif(data)
    orientation: int | None = None
    for ifd_name, entries in ifds.items():
        for tag, value in entries.items():
            if ifd_name == "Exif" and tag == EXIF_USER_COMMENT and isinstance(value, bytes):
                text = decode_user_comment(value)
                if text:
                    _set_chunk(raw, "UserComment", text, f"{source}:UserComment")
                continue
            if ifd_name in ("0th", "Image") and tag == EXIF_ORIENTATION and isinstance(value, int):
                orientation = value
            if tag in (EXIF_IFD_POINTER, 0x8825, 0xA005, 0x927C, 0x02BC):
                continue  # pointers, MakerNote and XMP are not shown as text
            if ifd_name == "0th" and isinstance(value, bytes):
                # ComfyUI writes one "key:<json>" string per entry here (prompt, workflow, …).
                text = value.decode("utf-8", errors="replace").strip("\x00")
                match = _KEY_JSON.match(text)
                if match:
                    key = match.group(1)
                    key = key.lower() if key.lower() in ("prompt", "workflow") else key
                    _set_chunk(raw, key, match.group(2), f"{source}:IFD0")
                    continue
            if ifd_name == "thumbnail":
                continue
            raw.info[f"EXIF {_tag_name(ifd_name, tag)}"] = _display(value)
    user_comment = raw.chunks.get("UserComment")
    if user_comment and user_comment.lstrip().startswith("{") and raw.chunk_sources.get("UserComment", "").startswith(source):
        # ComfyUI's AVIF writer may put {"prompt": …, "workflow": …} in the UserComment.
        try:
            import json

            obj = json.loads(user_comment)
        except ValueError:
            obj = None
        if isinstance(obj, dict):
            for key in ("prompt", "workflow"):
                if key in obj and key not in raw.chunks:
                    value = obj[key]
                    _set_chunk(raw, key, value if isinstance(value, str) else json.dumps(value), f"{source}:UserComment")
    return orientation


# -- PNG -------------------------------------------------------------------------------------------


def _set_chunk(raw: RawMetadata, key: str, value: str, source: str) -> None:
    if key in XMP_KEYS:
        raw.info["XMP"] = f"present ({len(value)} characters)"
        return
    if key not in raw.chunks:
        raw.chunks[key] = value
        raw.chunk_sources[key] = source


def _read_png(f: BinaryIO, raw: RawMetadata) -> int | None:
    """Walk the chunks of a PNG, reading text and header chunks and seeking past everything else."""
    if f.read(8) != PNG_SIGNATURE:
        raise UnsupportedFileError("Not a PNG file")
    raw.format = "PNG"
    orientation: int | None = None
    while True:
        header = f.read(8)
        if len(header) < 8:
            break
        length, ctype = struct.unpack(">I4s", header)
        if ctype in (b"IHDR", b"tEXt", b"zTXt", b"iTXt", b"comf", b"eXIf", b"acTL", b"pHYs", b"tIME"):
            data = f.read(length)
            f.seek(4, io.SEEK_CUR)
        else:
            f.seek(length + 4, io.SEEK_CUR)
            if ctype == b"IEND":
                break
            if ctype == b"iCCP":
                raw.info["ICC profile"] = "present"
            continue
        if len(data) < length:
            break
        try:
            if ctype == b"IHDR":
                width, height, depth, colour = struct.unpack(">IIBB", data[:10])
                raw.width, raw.height = width, height
                raw.mode = {0: "L", 2: "RGB", 3: "P", 4: "LA", 6: "RGBA"}.get(colour, str(colour))
                raw.info["Bit depth"] = str(depth)
            elif ctype == b"tEXt":
                key, _, value = data.partition(b"\x00")
                _set_chunk(raw, key.decode("latin-1"), decode_text(value), "png:tEXt")
            elif ctype == b"zTXt":
                key, _, rest = data.partition(b"\x00")
                _set_chunk(raw, key.decode("latin-1"), decode_text(_inflate(rest[1:])), "png:zTXt")
            elif ctype == b"iTXt":
                key, _, rest = data.partition(b"\x00")
                compressed, rest = rest[0], rest[2:]
                _lang, _, rest = rest.partition(b"\x00")
                _translated, _, value = rest.partition(b"\x00")
                if compressed:
                    value = _inflate(value)
                _set_chunk(raw, key.decode("latin-1"), value.decode("utf-8", errors="replace"), "png:iTXt")
            elif ctype == b"comf":
                # ComfyUI's animated PNG: "key\0<json>" after the image data.
                key, _, value = data.partition(b"\x00")
                _set_chunk(raw, key.decode("latin-1"), value.decode("utf-8", errors="replace"), "png:comf")
            elif ctype == b"eXIf":
                orientation = apply_exif(raw, data)
            elif ctype == b"acTL":
                raw.frames = max(1, struct.unpack(">I", data[:4])[0])
            elif ctype == b"pHYs":
                x, y, unit = struct.unpack(">IIB", data[:9])
                if unit == 1 and x:
                    raw.info["DPI"] = f"{round(x * 0.0254)}×{round(y * 0.0254)}"
            elif ctype == b"tIME":
                y, mo, d, h, mi, s = struct.unpack(">HBBBBB", data[:7])
                raw.info["PNG modified"] = f"{y:04d}-{mo:02d}-{d:02d} {h:02d}:{mi:02d}:{s:02d}"
        except (struct.error, zlib.error, IndexError) as e:
            logger.debug("Skipping a malformed %s chunk: %s", ctype, e)
    if raw.width is None:
        raise UnsupportedFileError("PNG without a header chunk")
    return orientation


# -- Everything else -------------------------------------------------------------------------------


def _read_pillow(f: BinaryIO, raw: RawMetadata) -> int | None:
    try:
        img = Image.open(f)
    except Exception as e:
        raise UnsupportedFileError(f"Not an image Pillow can read: {e}") from e
    with img:
        raw.format = img.format
        raw.width, raw.height = img.size
        raw.mode = img.mode
        info = dict(img.info)
        try:
            raw.frames = int(getattr(img, "n_frames", 1) or 1)
        except Exception:  # noqa: BLE001
            raw.frames = 1
    orientation: int | None = None
    exif = info.pop("exif", None)
    if isinstance(exif, bytes) and exif:
        orientation = apply_exif(raw, exif)
    comment = info.pop("comment", None)
    if isinstance(comment, bytes):
        comment = comment.decode("utf-8", errors="replace")
    if isinstance(comment, str) and comment.strip():
        _set_chunk(raw, "comment", comment, f"{(raw.format or 'image').lower()}:comment")
    for key in ("xmp", "XML:com.adobe.xmp"):
        if key in info:
            value = info.pop(key)
            raw.info["XMP"] = f"present ({len(value)} bytes)"
    if "icc_profile" in info:
        info.pop("icc_profile")
        raw.info["ICC profile"] = "present"
    if "dpi" in info:
        dpi = info.pop("dpi")
        if isinstance(dpi, tuple) and len(dpi) == 2:
            raw.info["DPI"] = f"{round(float(dpi[0]))}×{round(float(dpi[1]))}"
    for key, value in info.items():
        if isinstance(value, bytes):
            continue
        if isinstance(value, str) and key not in raw.chunks and len(value) > 0 and key in GENERATION_KEYS:
            _set_chunk(raw, key, value, f"{(raw.format or 'image').lower()}:info")
        elif isinstance(value, (str, int, float, tuple)):
            raw.info[str(key)] = _display(value)
    return orientation


def _finish(raw: RawMetadata, orientation: int | None) -> None:
    if orientation in (5, 6, 7, 8) and raw.width is not None and raw.height is not None:
        raw.width, raw.height = raw.height, raw.width
    if orientation and orientation != 1:
        raw.info["Orientation"] = str(orientation)
    if raw.frames > 1:
        raw.info["Frames"] = str(raw.frames)
    # Chunks such as Software, Title or Source are shown under Info as well.
    for key in ("Software", "Title", "Source", "Description", "Author", "Creation Time", "Copyright"):
        if key in raw.chunks and key not in raw.info:
            raw.info[key] = _display(raw.chunks[key])


def read_stream(f: BinaryIO) -> RawMetadata:
    """Read the containers of an open, seekable binary file."""
    raw = RawMetadata()
    start = f.tell()
    signature = f.read(8)
    f.seek(start)
    orientation = _read_png(f, raw) if signature == PNG_SIGNATURE else _read_pillow(f, raw)
    _finish(raw, orientation)
    return raw


def has_generation_text(raw: RawMetadata) -> bool:
    return any(key in GENERATION_KEYS or key.startswith("invokeai_") for key in raw.chunks)


def read_path(path: Path, siblings: set[str] | None = None, sidecar_extensions: list[str] | None = None) -> RawMetadata:
    """Read a file's containers, and its sidecars.

    ``siblings`` is the set of file names in the same folder when the caller already has it (a
    folder scan), which saves a ``stat`` per sidecar extension.
    """
    with open(path, "rb") as f:
        raw = read_stream(f)
    stem = path.stem
    for ext in sidecar_extensions if sidecar_extensions is not None else [".txt", ".json"]:
        name = stem + ext
        if name == path.name:
            continue
        present = name in siblings if siblings is not None else (path.parent / name).is_file()
        if present:
            raw.sidecars.append(name)
    txt = stem + ".txt"
    if txt in raw.sidecars and not has_generation_text(raw):
        try:
            with open(path.parent / txt, "rb") as f:
                data = f.read(MAX_SIDECAR_BYTES)
            _set_chunk(raw, "sidecar:txt", data.decode("utf-8", errors="replace"), "sidecar:txt")
        except OSError as e:
            logger.debug("Cannot read %s: %s", txt, e)
    return raw


def read_bytes(data: bytes) -> RawMetadata:
    """Read the containers of an in-memory file, such as an upload. No sidecars."""
    return read_stream(io.BytesIO(data))
