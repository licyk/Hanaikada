"""Copy an image's metadata into a 1×1 fixture, so tests hold real chunks without the pixels.

    python scripts/extract_metadata_fixture.py <source> <target.png|.jpg|.webp|.gif> [--compress]

- PNG → PNG: every text chunk (``tEXt``, ``zTXt``, ``iTXt``, ``comf``) and ``eXIf`` is copied
  byte for byte, so the chunk type is kept. ``--compress`` rewrites ``tEXt`` as ``zTXt`` to keep a
  fixture with a large workflow small; the text is unchanged.
- anything → JPEG or WebP: the source's infotext (``parameters``, else its UserComment) is written
  as the WebUI writes it: EXIF ``UserComment`` with the ``UNICODE`` prefix and UTF-16BE text.
- anything → GIF: the infotext as the GIF comment, as the WebUI does.
"""

import argparse
import io
import struct
import sys
import zlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PIL import Image

from hanaikada.core.metadata.containers import PNG_SIGNATURE, read_path

COPIED = {b"tEXt", b"zTXt", b"iTXt", b"comf", b"eXIf"}


def _chunk(ctype: bytes, data: bytes) -> bytes:
    return struct.pack(">I", len(data)) + ctype + data + struct.pack(">I", zlib.crc32(ctype + data) & 0xFFFFFFFF)


def source_chunks(source: Path, compress: bool) -> list[bytes]:
    out: list[bytes] = []
    with open(source, "rb") as f:
        if f.read(8) != PNG_SIGNATURE:
            raise SystemExit("PNG → PNG needs a PNG source")
        while True:
            header = f.read(8)
            if len(header) < 8:
                break
            length, ctype = struct.unpack(">I4s", header)
            data = f.read(length)
            f.read(4)
            if ctype in COPIED:
                if compress and ctype == b"tEXt":
                    key, _, value = data.partition(b"\x00")
                    out.append(_chunk(b"zTXt", key + b"\x00\x00" + zlib.compress(value, 9)))
                else:
                    out.append(_chunk(ctype, data))
            if ctype == b"IEND":
                break
    return out


def tiny_png(chunks: list[bytes]) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (1, 1), (128, 128, 128)).save(buffer, "PNG")
    data = buffer.getvalue()
    # Insert the copied chunks right after IHDR (8-byte signature + 25-byte IHDR chunk).
    return data[:33] + b"".join(chunks) + data[33:]


def user_comment_exif(text: str) -> bytes:
    import piexif
    import piexif.helper

    return piexif.dump({"Exif": {piexif.ExifIFD.UserComment: piexif.helper.UserComment.dump(text, encoding="unicode")}})


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python scripts/extract_metadata_fixture.py", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("source", type=Path)
    parser.add_argument("target", type=Path)
    parser.add_argument("--compress", action="store_true", help="store tEXt chunks as zTXt")
    args = parser.parse_args(argv)

    suffix = args.target.suffix.lower()
    args.target.parent.mkdir(parents=True, exist_ok=True)
    if suffix == ".png":
        args.target.write_bytes(tiny_png(source_chunks(args.source, args.compress)))
    else:
        raw = read_path(args.source)
        text = raw.chunks.get("parameters") or raw.chunks.get("UserComment") or raw.chunks.get("comment")
        if not text:
            raise SystemExit("The source has no infotext to write")
        image = Image.new("RGB", (1, 1), (128, 128, 128))
        if suffix in (".jpg", ".jpeg"):
            image.save(args.target, "JPEG", exif=user_comment_exif(text))
        elif suffix == ".webp":
            image.save(args.target, "WEBP", exif=user_comment_exif(text))
        elif suffix == ".gif":
            image.save(args.target, "GIF", comment=text)
        else:
            raise SystemExit(f"Unsupported target type: {suffix}")
    print(f"Wrote {args.target} ({args.target.stat().st_size} bytes)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
