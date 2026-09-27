"""Reading text out of image containers, before any platform logic."""

import io
import json

import pytest
from PIL import Image

from hanaikada.core.errors import UnsupportedFileError
from hanaikada.core.metadata import containers
from hanaikada.core.metadata.containers import decode_user_comment, read_bytes, read_path
from tests.helpers import FIXTURES, INFOTEXT, chunk, comfy_webp_exif, png_bytes, text_chunk, user_comment_exif, write_jpeg, write_png


@pytest.mark.parametrize("kind", ["tEXt", "zTXt", "iTXt", "iTXt-z"])
def test_png_text_chunks_of_every_kind(kind):
    value = "prompt, text" if kind in ("tEXt", "zTXt") else "猫耳, prompt 🌸"
    raw = read_bytes(png_bytes([text_chunk("parameters", value, kind)]))
    assert raw.format == "PNG"
    assert (raw.width, raw.height) == (2, 3)
    assert raw.chunks["parameters"] == value
    assert raw.chunk_sources["parameters"] == f"png:{kind.split('-')[0]}"


def test_png_text_after_the_image_data_is_found():
    # An APNG from ComfyUI's SaveAnimatedPNG puts "comf" chunks after IDAT.
    raw = read_bytes(png_bytes(after_idat=[text_chunk("prompt", '{"1": {"class_type": "KSampler", "inputs": {}}}', "comf"), text_chunk("late", "x")]))
    assert raw.chunk_sources["prompt"] == "png:comf"
    assert raw.chunks["late"] == "x"


def test_utf8_in_a_text_chunk_is_decoded():
    # tEXt is Latin-1 by the specification, but some writers put UTF-8 there.
    utf8 = chunk(b"tEXt", b"parameters\x00" + "blossom 桜".encode())
    latin1 = chunk(b"tEXt", b"Title\x00caf\xe9")
    raw = read_bytes(png_bytes([utf8, latin1]))
    assert raw.chunks["parameters"] == "blossom 桜"
    assert raw.chunks["Title"] == "café"


def test_forge_png_fixture():
    raw = read_path(FIXTURES / "forge_txt2img.png")
    assert list(raw.chunks) == ["parameters"]
    assert raw.chunks["parameters"].startswith("1girl,solo,cute")
    assert raw.chunk_sources["parameters"] == "png:tEXt"


@pytest.mark.parametrize("name", ["forge_txt2img.jpg", "forge_txt2img.webp"])
def test_webui_jpeg_and_webp_user_comment(name):
    raw = read_path(FIXTURES / name)
    png = read_path(FIXTURES / "forge_txt2img.png")
    assert raw.chunks["UserComment"] == png.chunks["parameters"]
    assert raw.chunk_sources["UserComment"] == "exif:UserComment"


def test_gif_comment():
    raw = read_path(FIXTURES / "forge_txt2img.gif")
    assert raw.chunks["comment"].startswith("1girl,solo,cute")
    assert raw.chunk_sources["comment"] == "gif:comment"


@pytest.mark.parametrize(
    ("data", "expected"),
    [
        (b"UNICODE\x00" + "Steps: 20, 桜".encode("utf-16-be"), "Steps: 20, 桜"),
        (b"UNICODE\x00" + "Steps: 20".encode("utf-16-le"), "Steps: 20"),
        (b"ASCII\x00\x00\x00Steps: 20", "Steps: 20"),
        (b"\x00" * 8 + b"plain", "plain"),
        (b"no prefix at all", "no prefix at all"),
    ],
)
def test_user_comment_encodings(data, expected):
    assert decode_user_comment(data) == expected


def test_ascii_user_comment_in_a_jpeg(tmp_path):
    path = write_jpeg(tmp_path / "a.jpg", "Steps: 20, Sampler: Euler, Seed: 1", encoding="ascii")
    assert read_path(path).chunks["UserComment"] == "Steps: 20, Sampler: Euler, Seed: 1"


def test_comfyui_webp_ifd0_entries(tmp_path):
    prompt = {"3": {"class_type": "KSampler", "inputs": {"seed": 5}}}
    path = tmp_path / "ComfyUI_00001_.webp"
    Image.new("RGB", (2, 2)).save(path, "WEBP", exif=comfy_webp_exif(prompt, {"nodes": []}))
    raw = read_path(path)
    assert json.loads(raw.chunks["prompt"]) == prompt
    assert json.loads(raw.chunks["workflow"]) == {"nodes": []}
    assert raw.chunk_sources["prompt"] == "exif:IFD0"


def test_manual_ifd_walk_is_the_fallback(monkeypatch):
    import piexif

    def broken(*_args, **_kwargs):
        raise ValueError("rejected")

    monkeypatch.setattr(piexif, "load", broken)
    exif = user_comment_exif("Steps: 3, Seed: 4, Sampler: Euler")
    buffer = io.BytesIO()
    Image.new("RGB", (2, 2)).save(buffer, "JPEG", exif=exif)
    assert read_bytes(buffer.getvalue()).chunks["UserComment"] == "Steps: 3, Seed: 4, Sampler: Euler"


def test_exif_orientation_swaps_the_reported_size(tmp_path):
    import piexif

    exif = piexif.dump({"0th": {piexif.ImageIFD.Orientation: 6}})
    path = write_jpeg(tmp_path / "rotated.jpg", exif=exif, size=(40, 10))
    raw = read_path(path)
    assert (raw.width, raw.height) == (10, 40)
    assert raw.info["Orientation"] == "6"


def test_txt_sidecar_is_read_when_the_file_has_no_text(tmp_path):
    image = write_png(tmp_path / "00001-1234.png")
    (tmp_path / "00001-1234.txt").write_text(INFOTEXT + "\n", encoding="utf-8")
    (tmp_path / "00001-1234.json").write_text("{}", encoding="utf-8")
    raw = read_path(image)
    assert raw.chunks["sidecar:txt"].startswith("1girl")
    assert raw.sidecars == ["00001-1234.txt", "00001-1234.json"]


def test_txt_sidecar_is_ignored_when_the_file_carries_text(tmp_path):
    image = write_png(tmp_path / "a.png", {"parameters": INFOTEXT})
    (tmp_path / "a.txt").write_text("something else", encoding="utf-8")
    raw = read_path(image, siblings={"a.png", "a.txt"})
    assert "sidecar:txt" not in raw.chunks
    assert raw.sidecars == ["a.txt"]


def test_not_an_image(tmp_path):
    path = tmp_path / "x.png"
    path.write_bytes(b"not an image at all")
    with pytest.raises(UnsupportedFileError):
        read_path(path)


def test_zip_bomb_is_capped(monkeypatch):
    monkeypatch.setattr(containers, "MAX_TEXT_BYTES", 1000)
    raw = read_bytes(png_bytes([text_chunk("big", "a" * 100_000, "zTXt")]))
    assert len(raw.chunks["big"]) == 1000


def test_xmp_is_reported_not_kept():
    raw = read_bytes(png_bytes([text_chunk("XML:com.adobe.xmp", "<x:xmpmeta/>", "iTXt")]))
    assert "XML:com.adobe.xmp" not in raw.chunks
    assert raw.info["XMP"].startswith("present")


def test_jpeg_xl_is_read_through_the_plugin(tmp_path):
    from hanaikada.core.imaging import Image as PluginImage
    from hanaikada.core.library.thumbnails import ThumbnailService

    source = tmp_path / "00001-1234567890.jxl"
    PluginImage.new("RGB", (600, 300), "red").save(source, "JXL", exif=user_comment_exif(INFOTEXT))
    raw = read_path(source)
    assert (raw.format, raw.width, raw.height) == ("JXL", 600, 300)
    assert raw.chunks["UserComment"] == INFOTEXT
    with PluginImage.open(ThumbnailService(tmp_path / "cache").get(source, 128).path) as thumb:
        assert thumb.size == (256, 128)
