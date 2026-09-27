"""Scanning, reconciling, tags and search against a temporary WebUI install."""

import os
import shutil
import sqlite3
import time
from datetime import datetime, timedelta, timezone

import pytest

from hanaikada.core.context import build_services
from hanaikada.core.errors import IndexBusyError, NotFoundError, ValidationError
from hanaikada.core.events.models import IndexChangedEvent, ScanCompletedEvent
from hanaikada.core.index.models import ScanRequest, SearchQuery, TagCreate, TagImagesRequest
from hanaikada.core.library.models import RootCreate
from tests.helpers import FIXTURES, INFOTEXT, write_png

DAY = "outputs/txt2img-images/2026-09-26"


def names(page) -> list[str]:
    return sorted(item.name for item in page.items)


def test_scan_indexes_only_output_folders(services, scanned):
    rows = services.db.fetchall("SELECT rel_path, platform FROM images ORDER BY rel_path")
    assert [(r["rel_path"], r["platform"]) for r in rows] == [
        ("outputs/extras-images/00000.png", "comfyui"),
        ("outputs/extras-images/invoke.png", "invokeai"),
        (f"{DAY}/00000-520469227.jpg", "sd-webui"),
        (f"{DAY}/00000-520469227.png", "sd-webui"),
        (f"{DAY}/00001-1234567890.png", "sd-webui"),
    ]
    summary = services.index.roots_summary()[0]
    assert (summary.images, summary.missing, summary.failed) == (5, 0, 0)


def test_rescan_reads_only_what_changed(services, scanned, webui_dir):
    events = []
    services.events.subscribe(events.append)
    services.index.scan_now(ScanRequest(root_id=scanned))
    done = [e for e in events if isinstance(e, ScanCompletedEvent)][-1]
    assert (done.files_seen, done.files_indexed) == (0, 0)  # no folder changed: nothing re-listed

    write_png(webui_dir / DAY / "00002-42.png", {"parameters": INFOTEXT.replace("Seed: 1234567890", "Seed: 42")})
    events.clear()
    services.index.scan_now(ScanRequest(root_id=scanned))
    done = [e for e in events if isinstance(e, ScanCompletedEvent)][-1]
    assert (done.files_seen, done.files_indexed) == (4, 1)
    changed = [e for e in events if isinstance(e, IndexChangedEvent)]
    assert changed and changed[0].added == [f"{DAY}/00002-42.png"]

    events.clear()
    services.index.scan_now(ScanRequest(root_id=scanned, full=True))
    done = [e for e in events if isinstance(e, ScanCompletedEvent)][-1]
    assert done.files_indexed == 6


def test_a_file_changed_in_place_is_read_again_when_its_folder_is_listed(services, scanned, webui_dir):
    path = webui_dir / DAY / "00001-1234567890.png"
    write_png(path, {"parameters": INFOTEXT.replace("Seed: 1234567890", "Seed: 7")})
    listing = services.library.list_entries(scanned, DAY)
    entry = next(f for f in listing.files if f.name == "00001-1234567890.png")
    assert entry.indexed is False  # size or mtime differ from the row
    services.index.index_files(scanned, [entry.path])
    assert services.index.record_by_path(scanned, entry.path).seed == 7


def test_missing_files_are_hidden_then_reconciled(services, scanned, webui_dir):
    (webui_dir / DAY / "00001-1234567890.png").unlink()
    services.index.scan_now(ScanRequest(root_id=scanned))
    row = services.db.fetchone("SELECT missing_since FROM images WHERE name = '00001-1234567890.png'")
    assert row["missing_since"] is not None
    assert "00001-1234567890.png" not in names(services.index.search(SearchQuery()))
    assert "00001-1234567890.png" in names(services.index.search(SearchQuery(include_missing=True)))
    old = (datetime.now(timezone.utc) - timedelta(days=8)).isoformat(timespec="seconds")
    services.db.execute("UPDATE images SET missing_since = ? WHERE name = '00001-1234567890.png'", (old,))
    services.index.scan_now(ScanRequest(root_id=scanned))
    assert services.db.fetchone("SELECT 1 FROM images WHERE name = '00001-1234567890.png'") is None


def test_a_file_that_comes_back_is_no_longer_missing(services, scanned, webui_dir):
    path = webui_dir / DAY / "00001-1234567890.png"
    data = path.read_bytes()
    path.unlink()
    services.index.scan_now(ScanRequest(root_id=scanned))
    path.write_bytes(data)
    # The folder mtime has a coarse clock tick; a real restore happens later than this test's.
    folder = path.parent
    os.utime(folder, ns=(folder.stat().st_atime_ns, folder.stat().st_mtime_ns + 10_000_000))
    services.index.scan_now(ScanRequest(root_id=scanned))
    assert services.index.record_by_path(scanned, f"{DAY}/00001-1234567890.png").missing is False


def test_a_removed_folder_marks_its_images_missing(services, scanned, webui_dir):
    shutil.rmtree(webui_dir / DAY)
    services.index.scan_now(ScanRequest(root_id=scanned))
    missing = services.db.fetchall("SELECT name FROM images WHERE missing_since IS NOT NULL")
    assert len(missing) == 3
    assert services.db.fetchone("SELECT 1 FROM folders WHERE rel_path = ?", (DAY,)) is None


def test_tags_are_derived_and_counted_by_trigger(services, scanned):
    lookup = {(t.type, t.name): t.count for t in services.index.list_tags(include_rare=True, limit=5000)}
    assert lookup[("platform", "sd-webui")] == 3
    assert lookup[("model", "noobaiXLNAIXL_vPred10Version")] == 3  # the Forge PNG, its JPEG twin, and the InvokeAI image
    assert lookup[("sampler", "euler_ancestral")] == 2
    assert lookup[("lora", "styleA")] == 1
    assert lookup[("prompt", "1girl")] == 5
    assert lookup[("size", "2x3")] == 1
    assert ("prompt", "masterpiece") in lookup  # (masterpiece:1.2) → masterpiece
    # A prompt tag seen once stays hidden until it reaches the threshold.
    visible = {t.name for t in services.index.list_tags("prompt", limit=5000)}
    rare = {name for (kind, name), count in lookup.items() if kind == "prompt" and count < 2}
    assert "1girl" in visible and rare and not rare & visible
    services.db.execute("DELETE FROM images WHERE name = 'invoke.png'")
    counts = {t.name: t.count for t in services.index.list_tags("platform")}
    assert "invokeai" not in counts


def test_custom_tags_follow_images_and_are_backed_up(services, scanned):
    favorite = services.index.find_tag("favorite", "custom")
    result = services.index.tag_images(favorite.id, TagImagesRequest(paths=[(scanned, f"{DAY}/00001-1234567890.png")]))
    assert (result.changed, result.tag.count) == (1, 1)
    assert services.index.tag_images(favorite.id, TagImagesRequest(paths=[(scanned, f"{DAY}/00001-1234567890.png")])).changed == 0
    record = services.index.record_by_path(scanned, f"{DAY}/00001-1234567890.png")
    assert record.tag_ids == [favorite.id]
    backup = (services.settings.data_dir / "tags-backup.json").read_text()
    assert f"{scanned}:{DAY}/00001-1234567890.png" in backup
    # A full rescan keeps custom tags.
    services.index.scan_now(ScanRequest(root_id=scanned, full=True))
    assert services.index.get_tag(favorite.id).count == 1
    assert services.index.tag_images(favorite.id, TagImagesRequest(image_ids=[record.id]), add=False).changed == 1


def test_custom_tags_are_restored_into_a_new_database(tmp_path, webui_dir):
    data = tmp_path / "data"
    s = build_services(data_dir=data, environ={})
    root_id = s.library.add_root(RootCreate(path=str(webui_dir), layout="sd-webui")).id
    s.index.scan_now(ScanRequest(root_id=root_id))
    tag = s.index.create_tag(TagCreate(name="keep", color="#ff0000"))
    s.index.tag_images(tag.id, TagImagesRequest(paths=[(root_id, f"{DAY}/00000-520469227.png")]))
    s.close()
    for name in ("hanaikada.db", "hanaikada.db-wal", "hanaikada.db-shm"):
        (data / name).unlink(missing_ok=True)
    s = build_services(data_dir=data, environ={})
    try:
        s.index.scan_now(ScanRequest(root_id=root_id))
        restored = s.index.find_tag("keep", "custom")
        assert (restored.count, restored.color) == (1, "#ff0000")
        assert s.db.get_client_state("hanaikada.tags_restore_pending") is False
    finally:
        s.close()


def test_search_every_filter(services, scanned):
    search = services.index.search
    assert search(SearchQuery()).total == 5
    assert search(SearchQuery(text="cherry blossoms")).total == 5
    assert names(search(SearchQuery(text="blossoms, BREAK"))) == ["00001-1234567890.png"]
    assert names(search(SearchQuery(text="LOWRES", text_in=["negative"]))) == ["00001-1234567890.png"]
    assert names(search(SearchQuery(text="lowres", text_in=["prompt"]))) == []
    assert names(search(SearchQuery(text="invoke", text_in=["name"]))) == ["invoke.png"]
    assert names(search(SearchQuery(text="stylea", text_in=["loras"]))) == ["00001-1234567890.png"]
    assert names(search(SearchQuery(regex=r"seed|licyk"))) == ["00000.png"]
    assert names(search(SearchQuery(root_ids=["nope"]))) == []
    assert len(search(SearchQuery(root_ids=[scanned], path_prefix="outputs/txt2img-images")).items) == 3
    assert names(search(SearchQuery(platforms=["comfyui", "invokeai"]))) == ["00000.png", "invoke.png"]
    assert names(search(SearchQuery(models=["animeModel_v1"]))) == ["00001-1234567890.png"]
    assert len(search(SearchQuery(samplers=["euler_ancestral"])).items) == 2
    assert len(search(SearchQuery(samplers=["Euler a"])).items) == 2
    assert names(search(SearchQuery(seed=1234567890))) == ["00001-1234567890.png"]
    assert names(search(SearchQuery(steps=(25, None)))) == ["00000.png", "00001-1234567890.png"]
    assert names(search(SearchQuery(cfg=(6.0, 7.0)))) == ["00001-1234567890.png"]
    assert names(search(SearchQuery(width=2, height=3))) == ["00001-1234567890.png"]
    assert len(search(SearchQuery(orientation="square")).items) == 4  # every fixture but one is 1×1
    assert names(search(SearchQuery(orientation="portrait"))) == ["00001-1234567890.png"]
    tomorrow = (datetime.now().astimezone() + timedelta(days=1)).date().isoformat()
    assert search(SearchQuery(date=(None, tomorrow))).total == 5
    assert search(SearchQuery(date=(tomorrow, None))).total == 0
    lora = services.index.find_tag("styleA", "lora")
    webui = services.index.find_tag("sd-webui", "platform")
    comfy = services.index.find_tag("comfyui", "platform")
    assert names(search(SearchQuery(all_tags=[lora.id, webui.id]))) == ["00001-1234567890.png"]
    assert len(search(SearchQuery(any_tags=[lora.id, comfy.id])).items) == 2
    assert search(SearchQuery(not_tags=[webui.id])).total == 2
    with pytest.raises(ValidationError):
        search(SearchQuery(regex="("))


@pytest.mark.parametrize("sort", ["mtime", "ctime", "name", "size", "seed", "random"])
def test_cursor_pages_cover_everything_once(services, scanned, sort):
    seen: list[int] = []
    query = SearchQuery(sort=sort, limit=2, random_seed=7)
    while True:
        page = services.index.search(query)
        seen.extend(i.id for i in page.items)
        if not page.next_cursor:
            break
        query = query.model_copy(update={"cursor": page.next_cursor})
    assert len(seen) == 5 and len(set(seen)) == 5


def test_cursor_is_stable_across_deletions(services, scanned):
    first = services.index.search(SearchQuery(sort="name", descending=False, limit=2))
    services.db.execute("DELETE FROM images WHERE id = ?", (first.items[0].id,))
    second = services.index.search(SearchQuery(sort="name", descending=False, limit=2, cursor=first.next_cursor))
    # Names sort "00000-…" before "00000.png": "-" is 0x2d, "." is 0x2e.
    assert [i.name for i in first.items] == ["00000-520469227.jpg", "00000-520469227.png"]
    assert [i.name for i in second.items] == ["00000.png", "00001-1234567890.png"]


def test_regex_pages_continue_from_the_last_row_read(services, scanned):
    page = services.index.search(SearchQuery(regex="1girl", limit=2, sort="name", descending=False))
    assert len(page.items) == 2 and page.next_cursor
    rest = services.index.search(SearchQuery(regex="1girl", limit=10, sort="name", descending=False, cursor=page.next_cursor))
    assert len(rest.items) == 3 and rest.next_cursor is None


def test_fts_and_like_give_the_same_rows(services, scanned):
    queries = [SearchQuery(text=t, text_in=fields) for t in ("cherry", "blossoms, hair", "BAD ANATOMY", "noobai", "ex") for fields in (None, ["prompt"], ["model"])]
    with_fts = [names(services.index.search(q)) for q in queries]
    services.db.fts = False
    without = [names(services.index.search(q)) for q in queries]
    assert with_fts == without


def test_facets_and_stats(services, scanned):
    facets = services.index.facets(SearchQuery())
    assert {f.value: f.count for f in facets.platforms} == {"sd-webui": 3, "comfyui": 1, "invokeai": 1}
    assert facets.total == 5
    assert services.index.facets(SearchQuery(platforms=["sd-webui"])).total == 3
    stats = services.index.stats()
    assert stats.total == 5 and sum(d.count for d in stats.per_day) == 5
    assert stats.loras[0].value in ("styleA", "ill-xl-01-ogipote_3", "anima_face_2-16") or stats.loras


def test_detail_raw_and_chunk_downloads(services, scanned):
    comfy = services.index.record_by_path(scanned, "outputs/extras-images/00000.png")
    detail = services.index.detail(comfy.id)
    assert detail.info.platform == "comfyui" and detail.chunks == ["postprocessing", "prompt", "workflow"]
    raw = services.index.raw(comfy.id)
    assert {c.key for c in raw.chunks} == {"prompt", "workflow", "postprocessing"}
    value, name = services.index.chunk(comfy.id, "workflow")
    assert name == "00000.workflow.json" and value.startswith("{")
    with pytest.raises(NotFoundError):
        services.index.chunk(comfy.id, "parameters")
    forge = services.index.record_by_path(scanned, f"{DAY}/00000-520469227.png")
    assert services.index.chunk(forge.id, "parameters")[1] == "00000-520469227.parameters.txt"
    neighbours = services.index.detail(forge.id).neighbours
    assert neighbours.previous is not None or neighbours.next is not None


def test_truncated_chunks_are_read_again_from_the_file(services, scanned):
    services.settings.update({"index": {"max_raw_bytes": 1024}})
    services.index.scan_now(ScanRequest(root_id=scanned, full=True))
    comfy = services.index.record_by_path(scanned, "outputs/extras-images/00000.png")
    stored = services.db.fetchone("SELECT length(value) AS n, truncated FROM image_text WHERE image_id = ? AND key = 'workflow'", (comfy.id,))
    assert stored["truncated"] == 1 and stored["n"] <= 1024
    value, _ = services.index.chunk(comfy.id, "workflow")
    assert len(value) == 204310
    assert services.index.reparse(scanned) == 5
    assert services.index.detail(comfy.id).info.seed == 26084


def test_reparse_uses_stored_chunks(services, scanned, webui_dir):
    services.db.execute("UPDATE images SET seed = NULL, info = '{}' WHERE name = '00001-1234567890.png'")
    (webui_dir / DAY / "00001-1234567890.png").unlink()  # not read: its chunks are stored whole
    assert services.index.reparse(scanned) == 5
    record = services.db.fetchone("SELECT seed FROM images WHERE name = '00001-1234567890.png'")
    assert record["seed"] == 1234567890


def test_by_path_indexes_on_demand_and_browse_only_roots(services, tmp_path):
    folder = tmp_path / "loose"
    write_png(folder / "a.png", {"parameters": INFOTEXT})
    root_id = services.library.add_root(RootCreate(path=str(folder), layout="custom", index=False)).id
    services.index.scan_now(ScanRequest())
    assert services.db.fetchone("SELECT COUNT(*) AS n FROM images")["n"] == 0  # browse-only: not scanned
    detail = services.index.by_path(root_id, "a.png")
    assert detail.info.seed == 1234567890
    assert services.db.fetchone("SELECT COUNT(*) AS n FROM images")["n"] == 1


def test_similar(services, scanned):
    forge = services.index.record_by_path(scanned, f"{DAY}/00000-520469227.png")
    assert names(services.index.similar(forge.id, "seed")) == ["00000-520469227.jpg", "00000-520469227.png"]
    assert len(services.index.similar(forge.id, "model").items) == 3


def test_broken_file_is_recorded_not_fatal(services, scanned, webui_dir):
    (webui_dir / DAY / "broken.png").write_bytes(b"\x89PNG\r\n\x1a\nnot really")
    (webui_dir / DAY / "bad-json.png").write_bytes((FIXTURES / "forge_txt2img.png").read_bytes())
    write_png(webui_dir / DAY / "bad-json.png", {"prompt": '{"1": {"class_type": "KSampler", oops'})
    events = []
    services.events.subscribe(events.append)
    services.index.scan_now(ScanRequest(root_id=scanned))
    done = [e for e in events if isinstance(e, ScanCompletedEvent)][-1]
    assert done.files_failed == 2
    broken = services.db.fetchone("SELECT platform, parse_error FROM images WHERE name = 'bad-json.png'")
    assert broken["platform"] == "comfyui" and broken["parse_error"].startswith("JSONDecodeError")
    assert services.db.fetchone("SELECT value FROM image_text i JOIN images m ON m.id = i.image_id WHERE m.name = 'bad-json.png'")["value"].endswith("oops")


def test_full_rebuild_is_refused_while_one_runs(services, scanned):
    services.index.scanner.submit(__import__("hanaikada.core.index.scanner", fromlist=["Job"]).Job("root", scanned, full=True), 20)
    with pytest.raises(IndexBusyError):
        services.index.request_scan(ScanRequest(root_id=scanned, full=True))
    services.index.request_scan(ScanRequest(root_id=scanned))  # an incremental scan just queues
    services.index.cancel()
    assert services.index.status().queued == 0


def test_background_scanner_and_watch(tmp_path, webui_dir):
    s = build_services(data_dir=tmp_path / "data", environ={}, settings_overrides={"index": {"watch_interval": 1}})
    try:
        root_id = s.library.add_root(RootCreate(path=str(webui_dir), layout="sd-webui")).id
        s.index.start()
        assert s.index.wait_idle(20)
        assert s.index.roots_summary()[0].images == 5
        time.sleep(0.05)
        write_png(webui_dir / DAY / "new.png", {"parameters": INFOTEXT})
        os.utime(webui_dir / DAY)
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline and s.index.record_by_path(root_id, f"{DAY}/new.png") is None:
            time.sleep(0.1)
        assert s.index.record_by_path(root_id, f"{DAY}/new.png") is not None
    finally:
        s.close()


def test_invokeai_boards_become_tags(services, tmp_path):
    root = tmp_path / "invokeai"
    images = root / "outputs" / "images"
    (images / "thumbnails").mkdir(parents=True)
    (root / "invokeai.yaml").write_text("")
    (root / "databases").mkdir()
    shutil.copy(FIXTURES / "invokeai_6.9.png", images / "a.png")
    shutil.copy(FIXTURES / "invokeai_6.9.png", images / "b.png")
    db = sqlite3.connect(root / "databases" / "invokeai.db")
    db.executescript(
        "CREATE TABLE images (image_name TEXT PRIMARY KEY, is_intermediate BOOLEAN, starred BOOLEAN);"
        "CREATE TABLE boards (board_id TEXT PRIMARY KEY, board_name TEXT);"
        "CREATE TABLE board_images (board_id TEXT, image_name TEXT PRIMARY KEY);"
        "INSERT INTO images VALUES ('a.png', 0, 1), ('b.png', 1, 0);"
        "INSERT INTO boards VALUES ('b1', 'Portraits');"
        "INSERT INTO board_images VALUES ('b1', 'a.png');"
    )
    db.commit()
    db.close()
    root_id = services.library.add_root(RootCreate(path=str(root))).id
    services.index.scan_now(ScanRequest(root_id=root_id))
    boards = {t.name: t.count for t in services.index.list_tags("board")}
    assert boards == {"Portraits": 1, "starred": 1, "intermediate": 1}
    # The database is only read.
    assert sqlite3.connect(root / "databases" / "invokeai.db").execute("SELECT COUNT(*) FROM images").fetchone()[0] == 2
