"""Library operations: listings, companions, file operations that the index follows, thumbnails."""

import io
import shutil
import threading
import zipfile

import pytest
from PIL import Image

from hanaikada.core.errors import ConflictError, InvalidPathError, NotFoundError, ValidationError
from hanaikada.core.index.models import ScanRequest, TagImagesRequest
from hanaikada.core.library.models import DeleteRequest, FolderCreate, PathRef, RenameRequest, RootCreate, RootUpdate, TransferRequest
from hanaikada.core.library.safety import resolve_in_root, split_rel, validate_name
from hanaikada.core.library.thumbnails import ThumbnailService
from tests.conftest import make_webui
from tests.helpers import FIXTURES, INFOTEXT

DAY = "outputs/txt2img-images/2026-09-26"


def ref(root_id: str, path: str) -> PathRef:
    return PathRef(root_id=root_id, path=path)


# -- roots and listings ------------------------------------------------------------------------------


def test_roots_detect_and_locked(services, webui_dir, tmp_path):
    root = services.library.add_root(RootCreate(path=str(webui_dir)))
    assert root.layout == "sd-webui"
    assert root.outputs == ["outputs/txt2img-images", "outputs/extras-images"]
    with pytest.raises(ConflictError):
        services.library.add_root(RootCreate(path=str(webui_dir)))
    with pytest.raises(InvalidPathError):
        services.library.add_root(RootCreate(path="relative/path"))
    updated = services.library.update_root(root.id, RootUpdate(name="Forge", index=False))
    assert (updated.name, updated.index) == ("Forge", False)
    services.library.roots_locked = True
    with pytest.raises(ConflictError):
        services.library.remove_root(root.id)


def test_listing_shows_only_the_layouts_folders(services, scanned):
    top = services.library.list_entries(scanned, "")
    assert [f.name for f in top.folders] == ["outputs"]
    assert top.files == []
    outputs = services.library.list_entries(scanned, "outputs")
    assert [(f.name, f.label) for f in outputs.folders] == [("extras-images", "extras"), ("txt2img-images", "txt2img")]
    with pytest.raises(NotFoundError):
        services.library.list_entries(scanned, "extensions/x")
    with pytest.raises(NotFoundError):
        services.library.file_path(scanned, "extensions/x/preview.png")


def test_listing_joins_the_index_and_covers(services, scanned):
    listing = services.library.list_entries(scanned, DAY, sort="name", descending=False)
    assert [f.name for f in listing.files] == ["00000-520469227.jpg", "00000-520469227.png", "00001-1234567890.png"]
    assert all(f.indexed and f.image is not None for f in listing.files)
    assert listing.files[2].image.seed == 1234567890
    folder = services.library.list_entries(scanned, "outputs/txt2img-images").folders[0]
    assert len(folder.cover) == 3 and all(c.version.isdigit() for c in folder.cover)


def test_listing_pages_and_sorts(services, scanned):
    first = services.library.list_entries(scanned, DAY, sort="name", descending=True, limit=2)
    assert first.total_files == 3 and first.next_cursor == "2"
    rest = services.library.list_entries(scanned, DAY, sort="name", descending=True, limit=2, cursor=first.next_cursor)
    assert [f.name for f in rest.files] == ["00000-520469227.jpg"] and rest.folders == [] and rest.next_cursor is None
    shuffled = [f.name for f in services.library.list_entries(scanned, DAY, sort="random", random_seed=3).files]
    assert sorted(shuffled) == sorted(f.name for f in first.files + rest.files)
    assert shuffled == [f.name for f in services.library.list_entries(scanned, DAY, sort="random", random_seed=3).files]


def test_listing_marks_gone_files_missing(services, scanned, webui_dir):
    (webui_dir / DAY / "00001-1234567890.png").unlink()
    services.library.list_entries(scanned, DAY)
    assert services.index.record_by_path(scanned, f"{DAY}/00001-1234567890.png").missing


def test_show_all_files(services, scanned, webui_dir):
    (webui_dir / DAY / "notes.md").write_text("x")
    assert "notes.md" not in [f.name for f in services.library.list_entries(scanned, DAY).files]
    services.settings.update({"library": {"show_all_files": True}})
    entry = next(f for f in services.library.list_entries(scanned, DAY).files if f.name == "notes.md")
    assert entry.kind == "file" and entry.image is None


def test_tree(services, scanned):
    tree = services.library.tree(scanned, depth=2)
    assert [c.name for c in tree.children] == ["outputs"]
    assert [c.name for c in tree.children[0].children] == ["extras-images", "txt2img-images"]
    assert tree.children[0].children[1].has_children and tree.children[0].children[1].children == []


# -- All folders ---------------------------------------------------------------------------------------


def _shown(combined) -> list[tuple[str, str | None, str, bool]]:
    return [(f.display_name, f.label, f.path, f.is_root) for f in combined.folders]


def test_combined_view_is_off_by_default(services):
    assert services.settings.settings.library.combined_view is False


def test_combined_lists_every_roots_output_folders(services, webui_root, webui_dir, tmp_path):
    comfy = tmp_path / "ComfyUI"
    (comfy / "output").mkdir(parents=True)
    (comfy / "main.py").write_text("")
    (comfy / "folder_paths.py").write_text("")
    shutil.copy(FIXTURES / "forge_txt2img.png", comfy / "output" / "ComfyUI_00001_.png")
    comfy_id = services.library.add_root(RootCreate(path=str(comfy), name="ComfyUI")).id
    # A plain folder is its own output folder: one entry, named after the root.
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    shutil.copy(FIXTURES / "forge_txt2img.png", scratch / "a.png")
    scratch_id = services.library.add_root(RootCreate(path=str(scratch), name="Scratch")).id
    # A root inside another root's output folder is reached through the outer one.
    services.library.add_root(RootCreate(path=str(webui_dir / DAY), name="Day"))
    # A root that has gone away is reported, not raised.
    gone = tmp_path / "gone"
    gone.mkdir()
    gone_id = services.library.add_root(RootCreate(path=str(gone), name="Gone")).id
    gone.rmdir()

    combined = services.library.list_combined()
    assert _shown(combined) == [
        ("txt2img-images", "txt2img", "outputs/txt2img-images", False),
        ("extras-images", "extras", "outputs/extras-images", False),
        ("output", "output", "output", False),
        ("Scratch", None, "", True),
    ]
    assert [f.root_id for f in combined.folders] == [webui_root, webui_root, comfy_id, scratch_id]
    assert combined.missing_roots == [gone_id]
    # Each entry opens in its own root, with covers from it.
    assert combined.folders[2].cover and combined.folders[2].cover[0].path == "output/ComfyUI_00001_.png"
    assert services.library.list_entries(comfy_id, combined.folders[2].path).total_files == 1


def test_combined_tells_equal_names_apart(services, webui_root, tmp_path):
    other = make_webui(tmp_path / "forge")
    services.library.add_root(RootCreate(path=str(other), name="webui", layout="sd-webui"))
    names = [f.display_name for f in services.library.list_combined().folders]
    assert names == ["txt2img-images (webui)", "extras-images (webui)", "txt2img-images (webui 2)", "extras-images (webui 2)"]


def test_the_combined_id_is_reserved(services, tmp_path):
    with pytest.raises(ValidationError):
        services.library.add_root(RootCreate(path=str(tmp_path)), root_id="*")


def test_path_safety():
    with pytest.raises(InvalidPathError):
        split_rel("../x")
    with pytest.raises(InvalidPathError):
        split_rel("/etc/passwd")
    with pytest.raises(InvalidPathError):
        split_rel("C:/Windows")
    for bad in ("", "..", "a/b", "CON", "x.", " y", "a\x00"):
        with pytest.raises(InvalidPathError):
            validate_name(bad)


def test_symlink_escape_refused_unless_followed(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (root / "link").symlink_to(outside)
    with pytest.raises(InvalidPathError):
        resolve_in_root(root, "link", follow_symlinks=False)
    assert resolve_in_root(root, "link", follow_symlinks=True) == root.resolve() / "link"


# -- operations ----------------------------------------------------------------------------------------


def test_move_carries_sidecars_and_the_index_follows(services, scanned, webui_dir):
    (webui_dir / DAY / "00001-1234567890.txt").write_text(INFOTEXT)
    favorite = services.index.find_tag("favorite", "custom")
    services.index.tag_images(favorite.id, TagImagesRequest(paths=[(scanned, f"{DAY}/00001-1234567890.png")]))
    before = services.index.record_by_path(scanned, f"{DAY}/00001-1234567890.png")
    result = services.library.transfer(TransferRequest(items=[ref(scanned, f"{DAY}/00001-1234567890.png")], dest_root_id=scanned, dest_dir="outputs/extras-images"))
    assert result.paths == [ref(scanned, "outputs/extras-images/00001-1234567890.png")]
    assert (webui_dir / "outputs/extras-images/00001-1234567890.txt").is_file()
    after = services.index.record_by_path(scanned, "outputs/extras-images/00001-1234567890.png")
    assert after is not None and after.id == before.id and after.tag_ids == [favorite.id]
    assert services.index.record_by_path(scanned, f"{DAY}/00001-1234567890.png") is None


def test_the_4chan_jpeg_twin_is_not_a_companion(services, scanned, webui_dir):
    (webui_dir / DAY / "00000-520469227.txt").write_text("shared")
    services.library.transfer(TransferRequest(items=[ref(scanned, f"{DAY}/00000-520469227.png")], dest_root_id=scanned, dest_dir="outputs/extras-images"))
    assert (webui_dir / DAY / "00000-520469227.jpg").is_file()
    assert (webui_dir / DAY / "00000-520469227.txt").is_file()  # still shared with the JPEG
    services.library.transfer(TransferRequest(items=[ref(scanned, f"{DAY}/00000-520469227.jpg")], dest_root_id=scanned, dest_dir="outputs/extras-images", on_conflict="rename"))
    assert (webui_dir / "outputs/extras-images/00000-520469227.txt").is_file()


def test_nothing_is_overwritten(services, scanned):
    request = TransferRequest(items=[ref(scanned, f"{DAY}/00000-520469227.png")], dest_root_id=scanned, dest_dir=DAY)
    with pytest.raises(ConflictError):
        services.library.transfer(request, copy=True)
    renamed = services.library.transfer(request.model_copy(update={"on_conflict": "rename"}), copy=True)
    assert renamed.paths[0].path == f"{DAY}/00000-520469227_1.png"
    skipped = services.library.transfer(request.model_copy(update={"on_conflict": "skip"}), copy=True)
    assert skipped.skipped and not skipped.paths


def test_continue_on_error_reports_each_failure(services, scanned):
    request = TransferRequest(
        items=[ref(scanned, f"{DAY}/nope.png"), ref(scanned, f"{DAY}/00001-1234567890.png")], dest_root_id=scanned, dest_dir="outputs/extras-images", continue_on_error=True
    )
    result = services.library.transfer(request)
    assert [e.code for e in result.errors] == ["not_found"]
    assert result.paths == [ref(scanned, "outputs/extras-images/00001-1234567890.png")]


def test_rename_keeps_sidecars_and_row(services, scanned, webui_dir):
    (webui_dir / DAY / "00001-1234567890.json").write_text("{}")
    before = services.index.record_by_path(scanned, f"{DAY}/00001-1234567890.png")
    result = services.library.rename(RenameRequest(root_id=scanned, path=f"{DAY}/00001-1234567890.png", new_name="best"))
    assert result.paths[0].path == f"{DAY}/best.png"
    assert (webui_dir / DAY / "best.json").is_file()
    assert services.index.record_by_path(scanned, f"{DAY}/best.png").id == before.id
    kept = services.library.rename(RenameRequest(root_id=scanned, path=f"{DAY}/best.png", new_name="best.v2"))
    assert kept.paths[0].path == f"{DAY}/best.v2.png"  # an unknown suffix is part of the stem
    services.library.rename(RenameRequest(root_id=scanned, path=f"{DAY}/best.v2.png", new_name="best.png"))
    folder = services.library.rename(RenameRequest(root_id=scanned, path=DAY, new_name="2026-09-27"))
    assert folder.paths[0].path == "outputs/txt2img-images/2026-09-27"
    assert services.index.record_by_path(scanned, "outputs/txt2img-images/2026-09-27/best.png").id == before.id


def test_delete_removes_row_tags_sidecars_and_thumbnails(services, scanned, webui_dir):
    (webui_dir / DAY / "00001-1234567890.txt").write_text(INFOTEXT)
    favorite = services.index.find_tag("favorite", "custom")
    services.index.tag_images(favorite.id, TagImagesRequest(paths=[(scanned, f"{DAY}/00001-1234567890.png")]))
    thumb = services.library.thumbnail(scanned, f"{DAY}/00001-1234567890.png", 256)
    assert thumb.path.exists()
    services.library.delete(DeleteRequest(items=[ref(scanned, f"{DAY}/00001-1234567890.png")], permanent=True))
    assert not (webui_dir / DAY / "00001-1234567890.png").exists()
    assert not (webui_dir / DAY / "00001-1234567890.txt").exists()
    assert not thumb.path.exists()
    assert services.index.record_by_path(scanned, f"{DAY}/00001-1234567890.png") is None
    assert services.index.get_tag(favorite.id).count == 0
    with pytest.raises(InvalidPathError):
        services.library.delete(DeleteRequest(items=[ref(scanned, "")]))


def test_delete_to_trash_falls_back_to_the_data_directory(services, scanned, webui_dir, monkeypatch):
    import send2trash

    def refuse(_path):
        raise OSError("no trash here")

    monkeypatch.setattr(send2trash, "send2trash", refuse)
    result = services.library.delete(DeleteRequest(items=[ref(scanned, f"{DAY}/00001-1234567890.png")]))
    assert result.trashed_to and result.trashed_to[0].startswith(str(services.settings.data_dir / "trash"))


def test_create_folder_and_upload_index_the_file(services, scanned):
    created = services.library.create_folder(FolderCreate(root_id=scanned, path="outputs/txt2img-images", name="new"))
    assert created.path == "outputs/txt2img-images/new"
    with pytest.raises(InvalidPathError):
        services.library.create_folder(FolderCreate(root_id=scanned, path="", name="elsewhere"))
    data = (FIXTURES / "forge_txt2img.png").read_bytes()
    writer = services.library.open_upload(scanned, created.path, "up.png", total=len(data))
    writer.write(data)
    uploaded = writer.commit()
    assert services.index.record_by_path(scanned, uploaded.path).seed == 520469227
    with pytest.raises(ConflictError):
        services.library.open_upload(scanned, created.path, "up.png")
    with pytest.raises(ValidationError):
        services.library.open_upload(scanned, created.path, "virus.exe")


def test_zip_stream(services, scanned):
    data = b"".join(services.library.zip_stream([ref(scanned, f"{DAY}/00001-1234567890.png"), ref(scanned, "outputs/extras-images")]))
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        assert sorted(archive.namelist()) == ["00001-1234567890.png", "extras-images/00000.png", "extras-images/invoke.png"]
        assert archive.read("00001-1234567890.png") == (services.library.file_path(scanned, f"{DAY}/00001-1234567890.png")).read_bytes()


def test_invokeai_thumbnail_follows_and_seeds(services, tmp_path):
    root = tmp_path / "invokeai"
    images = root / "outputs" / "images"
    (images / "thumbnails").mkdir(parents=True)
    (images / "sub").mkdir()
    (root / "invokeai.yaml").write_text("")
    shutil.copy(FIXTURES / "invokeai_6.9.png", images / "uuid.png")
    Image.new("RGB", (256, 200), (250, 0, 0)).save(images / "thumbnails" / "uuid.webp", "WEBP")
    root_id = services.library.add_root(RootCreate(path=str(root))).id
    services.index.scan_now(ScanRequest(root_id=root_id))
    assert [f.name for f in services.library.list_entries(root_id, "outputs/images").files] == ["uuid.png"]
    assert services.library.companions(root_id, "outputs/images/uuid.png") == ["outputs/images/thumbnails/uuid.webp"]
    thumb = services.library.thumbnail(root_id, "outputs/images/uuid.png", 128)
    with Image.open(thumb.path) as img:
        red, green, _ = img.convert("RGB").getpixel((0, 0))
        assert red > 200 and green < 50  # made from InvokeAI's red thumbnail, not the grey 1×1 PNG
    services.library.transfer(TransferRequest(items=[ref(root_id, "outputs/images/uuid.png")], dest_root_id=root_id, dest_dir="outputs/images/sub"))
    assert (images / "thumbnails" / "sub" / "uuid.webp").is_file()
    services.library.rename(RenameRequest(root_id=root_id, path="outputs/images/sub/uuid.png", new_name="renamed"))
    assert (images / "thumbnails" / "sub" / "renamed.webp").is_file()
    services.library.delete(DeleteRequest(items=[ref(root_id, "outputs/images/sub/renamed.png")], permanent=True))
    assert not (images / "thumbnails" / "sub" / "renamed.webp").exists()


# -- thumbnails -----------------------------------------------------------------------------------------


def test_thumbnail_sizes_and_cache_key(tmp_path):
    source = tmp_path / "wide.png"
    Image.new("RGB", (1200, 600)).save(source)
    service = ThumbnailService(tmp_path / "cache")
    small = service.get(source, 100)
    with Image.open(small.path) as img:
        assert img.size == (256, 128)  # rounded up to 128; the short side gets it
    again = service.get(source, 128)
    assert again.etag == small.etag
    source.write_bytes(source.read_bytes() + b"\x00")
    assert service.get(source, 128).etag != small.etag  # size or mtime changed: a new key
    tall = tmp_path / "tall.jpg"
    Image.new("RGB", (600, 3000)).save(tall, "JPEG")
    with Image.open(service.get(tall, 256).path) as img:
        assert img.size == (102, 512)


def test_large_png_is_decoded_once(tmp_path, monkeypatch):
    from hanaikada.core.library import thumbnails

    monkeypatch.setattr(thumbnails, "LARGE_IMAGE_PIXELS", 10_000)
    source = tmp_path / "big.png"
    Image.new("RGB", (400, 400)).save(source)
    service = ThumbnailService(tmp_path / "cache")
    service.get(source, 128)
    assert len(list((tmp_path / "cache").glob("*/*.webp"))) == 2  # the 768 master and the 128


def test_thumbnail_stampede_generates_once(tmp_path, monkeypatch):
    source = tmp_path / "a.png"
    Image.new("RGB", (300, 300)).save(source)
    service = ThumbnailService(tmp_path / "cache", workers=4)
    calls = []
    original = service._write

    def counting(*args):
        calls.append(args)
        original(*args)

    monkeypatch.setattr(service, "_write", counting)
    threads = [threading.Thread(target=service.get, args=(source, 256)) for _ in range(16)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(calls) == 1


def test_sweep_and_forget(tmp_path):
    service = ThumbnailService(tmp_path / "cache")
    sources = []
    for i in range(3):
        path = tmp_path / f"{i}.png"
        Image.new("RGB", (300, 300), (i, i, i)).save(path)
        sources.append(path)
        service.get(path, 256)
    files, size = service.usage()
    assert files == 3
    assert service.sweep(size - 1) >= 1
    service.get(sources[0], 128)
    assert service.forget(sources[0], sources[0].stat()) >= 1
