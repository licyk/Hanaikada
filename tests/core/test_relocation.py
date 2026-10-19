"""The data folder and image roots move: the index, tags and thumbnails follow."""

import shutil
from pathlib import Path

from hanaikada.core.context import build_services
from hanaikada.core.index.models import ScanRequest, SearchQuery, TagImagesRequest
from hanaikada.core.library.models import RootCreate, RootUpdate
from hanaikada.core.settings.service import SettingsService
from hanaikada.embed import HanaikadaServer, ImageRoot
from tests.conftest import make_webui

DAY = "outputs/txt2img-images/2026-09-26"
IMAGE = f"{DAY}/00001-1234567890.png"


def _favourite(services, root_id: str) -> int:
    favorite = services.index.find_tag("favorite", "custom")
    services.index.tag_images(favorite.id, TagImagesRequest(paths=[(root_id, IMAGE)]))
    return favorite.id


def test_the_data_folder_can_be_moved_or_copied(tmp_path):
    webui = make_webui(tmp_path / "webui")
    first = tmp_path / "a" / "data"
    s = build_services(data_dir=first, environ={})
    root_id = s.library.add_root(RootCreate(path=str(webui), layout="sd-webui")).id
    s.index.scan_now(ScanRequest(root_id=root_id))
    tag_id = _favourite(s, root_id)
    s.close()
    copy = tmp_path / "copy"
    shutil.copytree(first, copy)
    moved = tmp_path / "b" / "data"
    moved.parent.mkdir()
    shutil.move(str(first), str(moved))
    for data in (moved, copy):
        s = build_services(data_dir=data, environ={})
        try:
            record = s.index.record_by_path(root_id, IMAGE)
            assert record is not None and not record.missing and record.tag_ids == [tag_id]
            assert s.index.search(SearchQuery()).total == 5
        finally:
            s.close()


def test_repointing_a_root_keeps_its_rows_and_tags(services, tmp_path):
    webui = make_webui(tmp_path / "webui")
    root_id = services.library.add_root(RootCreate(path=str(webui), layout="sd-webui")).id
    services.index.scan_now(ScanRequest(root_id=root_id))
    tag_id = _favourite(services, root_id)
    before = services.index.record_by_path(root_id, IMAGE)
    moved = tmp_path / "disk2" / "webui"
    moved.parent.mkdir()
    shutil.move(str(webui), str(moved))
    services.library.update_root(root_id, RootUpdate(path=str(moved)))
    services.index.scan_now(ScanRequest(root_id=root_id))
    after = services.index.record_by_path(root_id, IMAGE)
    assert after is not None and after.id == before.id and not after.missing and after.tag_ids == [tag_id]
    assert services.index.get_tag(tag_id).count == 1
    assert services.index.search(SearchQuery()).total == 5


def test_repointing_to_a_folder_without_the_files_hides_their_rows(services, tmp_path):
    webui = make_webui(tmp_path / "webui")
    root_id = services.library.add_root(RootCreate(path=str(webui), layout="sd-webui")).id
    services.index.scan_now(ScanRequest(root_id=root_id))
    _favourite(services, root_id)
    empty = tmp_path / "empty"
    empty.mkdir()
    services.library.update_root(root_id, RootUpdate(path=str(empty), layout="custom"))
    services.index.scan_now(ScanRequest(root_id=root_id))
    assert services.index.search(SearchQuery()).total == 0
    # Kept (missing) with their tags for the grace period, should the folder come back.
    record = services.index.record_by_path(root_id, IMAGE)
    assert record is not None and record.missing and record.tag_ids


def test_rows_of_roots_no_longer_configured_are_hidden(tmp_path):
    webui = make_webui(tmp_path / "webui")
    data = tmp_path / "data"
    s = build_services(data_dir=data, environ={})
    root_id = s.library.add_root(RootCreate(path=str(webui), layout="sd-webui")).id
    s.index.scan_now(ScanRequest(root_id=root_id))
    s.settings.mutate(lambda d: d["paths"].update(roots=[]))  # removed by hand, not through remove_root
    s.close()
    s = build_services(data_dir=data, environ={})
    try:
        assert s.index.search(SearchQuery()).total == 0
        assert s.db.fetchone("SELECT COUNT(*) AS n FROM images")["n"] == 5  # kept, hidden
    finally:
        s.close()


def test_a_host_root_with_its_own_id_follows_its_folder(tmp_path):
    webui = make_webui(tmp_path / "webui")
    data = tmp_path / "data"
    server = HanaikadaServer(data_dir=data, image_roots=[ImageRoot(webui, layout="sd-webui", id="forge")], port=0)
    s = server._build()
    s.index.scan_now(ScanRequest(root_id="forge"))
    tag_id = _favourite(s, "forge")
    s.close()
    moved = tmp_path / "moved" / "webui"
    moved.parent.mkdir()
    shutil.move(str(webui), str(moved))
    server = HanaikadaServer(data_dir=data, image_roots=[ImageRoot(moved, layout="sd-webui", id="forge")], port=0)
    s = server._build()
    try:
        assert [r.id for r in s.library.list_roots()] == ["forge"]
        assert Path(s.library.root("forge").path) == moved.resolve()
        s.index.scan_now(ScanRequest(root_id="forge"))
        record = s.index.record_by_path("forge", IMAGE)
        assert record is not None and not record.missing and record.tag_ids == [tag_id]
    finally:
        s.close()


def test_a_relative_settings_file_is_fixed_at_start(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    settings = SettingsService(data_dir=tmp_path / "data", settings_path=Path("conf/hanaikada.toml"), environ={})
    assert settings.path == tmp_path.resolve() / "conf" / "hanaikada.toml"
