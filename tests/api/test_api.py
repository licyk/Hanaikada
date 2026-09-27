"""The API over TestClient: error mapping, security, uploads, on-demand indexing, paging, downloads."""

import pytest
from fastapi.testclient import TestClient

from hanaikada.api.app import create_app
from hanaikada.core.index.models import ScanRequest
from tests.conftest import make_webui
from tests.helpers import FIXTURES

ORIGIN = {"origin": "http://localhost"}
DAY = "outputs/txt2img-images/2026-09-26"


@pytest.fixture
def app(services):
    return create_app(services, bound_host="127.0.0.1", start_scanner=False, serve_ui=False)


@pytest.fixture
def client(app):
    with TestClient(app, base_url="http://localhost") as c:
        yield c


@pytest.fixture
def root(client, services, tmp_path):
    webui = make_webui(tmp_path / "webui")
    r = client.post("/api/v1/library/roots", json={"path": str(webui)}, headers=ORIGIN)
    assert r.status_code == 201, r.text
    root_id = r.json()["id"]
    assert r.json()["layout"] == "sd-webui"
    services.index.scan_now(ScanRequest(root_id=root_id))
    return root_id


def test_health_meta_version(client):
    assert client.get("/api/v1/app/health").json() == {"status": "ok", "auth_required": False}
    meta = client.get("/api/v1/app/meta").json()
    assert meta["fts"] is True and meta["local"] is True and "comfyui" in meta["platforms"]
    assert client.get("/api/v1/app/version").json()["version"]


def test_error_shape(client):
    r = client.get("/api/v1/library/roots/nope/entries")
    assert r.status_code == 404
    assert r.json()["code"] == "not_found" and "nope" in r.json()["message"]
    assert client.get("/api/v1/images/999").json()["code"] == "not_found"
    r = client.post("/api/v1/search", json={"regex": "("})
    assert r.status_code == 400 and r.json()["code"] == "invalid_input"


def test_settings_and_client_state(client):
    r = client.patch("/api/v1/settings", json={"server": {"access_token": "SECRET"}}, headers=ORIGIN)
    assert r.status_code == 200 and "SECRET" not in r.text and r.json()["server"]["access_token_configured"] is True
    assert client.patch("/api/v1/settings", json={"paths": {}}, headers=ORIGIN).status_code in (400, 401)


def test_client_state(client):
    assert client.get("/api/v1/client-state/prefs").json() is None
    assert client.put("/api/v1/client-state/prefs", json={"theme": "dark"}, headers=ORIGIN).status_code == 200
    assert client.get("/api/v1/client-state/prefs").json() == {"theme": "dark"}


def test_host_origin_and_token(app, services):
    with TestClient(app, base_url="http://evil.example") as c:
        assert c.get("/api/v1/app/health").status_code == 400
    with TestClient(app, base_url="http://localhost") as c:
        assert c.post("/api/v1/tags", json={"name": "x"}, headers={"origin": "http://evil.example"}).status_code == 403
        assert c.post("/api/v1/tags", json={"name": "x"}, headers={"sec-fetch-site": "cross-site"}).status_code == 403
        assert c.post("/api/v1/tags", json={"name": "x"}).status_code == 201  # no browser headers: not a page
        services.settings.update({"server": {"access_token": "tok"}})
        assert c.get("/api/v1/app/health").status_code == 200
        assert c.get("/api/v1/tags").status_code == 401
        assert c.get("/api/v1/tags", headers={"authorization": "Bearer tok"}).status_code == 200
        assert c.get("/api/v1/tags", params={"token": "tok"}).status_code == 200
        c.cookies.set("hanaikada_token", "tok")
        assert c.get("/api/v1/tags").status_code == 200


def test_listing_by_path_and_detail(client, root):
    listing = client.get(f"/api/v1/library/roots/{root}/entries", params={"path": DAY, "sort": "name", "desc": False}).json()
    assert [f["name"] for f in listing["files"]] == ["00000-520469227.jpg", "00000-520469227.png", "00001-1234567890.png"]
    entry = listing["files"][1]
    assert entry["indexed"] and entry["image"]["platform"] == "sd-webui"
    detail = client.get("/api/v1/images/by-path", params={"root_id": root, "path": entry["path"]}).json()
    assert detail["info"]["seed"] == 520469227 and detail["record"]["id"] == entry["image"]["id"]
    assert client.get(f"/api/v1/images/{detail['record']['id']}").json()["info"]["model"]["name"] == "noobaiXLNAIXL_vPred10Version"
    tree = client.get(f"/api/v1/library/roots/{root}/tree", params={"depth": 3}).json()
    assert tree["children"][0]["name"] == "outputs"


def test_combined_entries(client, root):
    combined = client.get("/api/v1/library/combined/entries").json()
    assert [(f["display_name"], f["root_id"], f["path"], f["is_root"]) for f in combined["folders"]] == [
        ("txt2img-images", root, "outputs/txt2img-images", False),
        ("extras-images", root, "outputs/extras-images", False),
    ]
    assert combined["folders"][1]["cover"] and combined["missing_roots"] == []


def test_by_path_indexes_a_new_file(client, root, services, tmp_path):
    new = services.library.root_path(root) / DAY / "fresh.png"
    new.write_bytes((FIXTURES / "forge_txt2img.png").read_bytes())
    listing = client.get(f"/api/v1/library/roots/{root}/entries", params={"path": DAY}).json()
    assert next(f for f in listing["files"] if f["name"] == "fresh.png")["indexed"] is False
    detail = client.get("/api/v1/images/by-path", params={"root_id": root, "path": f"{DAY}/fresh.png"}).json()
    assert detail["info"]["platform"] == "sd-webui"


def test_file_thumbnail_caching(client, root):
    entry = client.get(f"/api/v1/library/roots/{root}/entries", params={"path": DAY}).json()["files"][0]
    params = {"path": entry["path"], "t": entry["version"]}
    r = client.get(f"/api/v1/library/roots/{root}/file", params=params)
    assert r.status_code == 200 and "immutable" in r.headers["cache-control"] and r.headers["content-disposition"].startswith("inline")
    assert client.get(f"/api/v1/library/roots/{root}/file", params={**params, "download": True}).headers["content-disposition"].startswith("attachment")
    assert client.get(f"/api/v1/library/roots/{root}/file", params={"path": entry["path"]}).headers["cache-control"] == "private, no-cache"
    thumb = client.get(f"/api/v1/library/roots/{root}/thumbnail", params={**params, "size": 200})
    assert thumb.status_code == 200 and thumb.headers["content-type"] == "image/webp"
    again = client.get(f"/api/v1/library/roots/{root}/thumbnail", params={**params, "size": 200}, headers={"if-none-match": thumb.headers["etag"]})
    assert again.status_code == 304 and again.content == b""
    assert client.get(f"/api/v1/library/roots/{root}/file", params={"path": "config.json"}).status_code == 404


def test_raw_and_chunk_downloads(client, root, services):
    comfy = services.index.record_by_path(root, "outputs/extras-images/00000.png")
    raw = client.get(f"/api/v1/images/{comfy.id}/raw").json()
    assert {c["key"] for c in raw["chunks"]} == {"prompt", "workflow", "postprocessing"}
    r = client.get(f"/api/v1/images/{comfy.id}/raw/workflow")
    assert r.headers["content-type"] == "application/json" and 'filename="00000.workflow.json"' in r.headers["content-disposition"]
    forge = services.index.record_by_path(root, f"{DAY}/00000-520469227.png")
    r = client.get(f"/api/v1/images/{forge.id}/raw/parameters")
    assert r.headers["content-type"].startswith("text/plain") and r.text.startswith("1girl")


def test_parse_an_upload(client):
    r = client.post("/api/v1/images/parse", params={"name": "2026-05-10_19-05-35_00001_.png"}, content=(FIXTURES / "2026-05-10_19-05-35_00001_.png").read_bytes(), headers=ORIGIN)
    assert r.status_code == 200
    body = r.json()
    assert body["info"]["platform"] == "comfyui" and body["info"]["seed"] == 399393160470141
    assert {c["key"] for c in body["raw"]["chunks"]} == {"prompt", "workflow"}
    bad = client.post("/api/v1/images/parse", content=b"nope", headers=ORIGIN)
    assert bad.status_code == 400 and bad.json()["code"] == "unsupported_file"


def test_search_paging_facets_stats(client, root):
    first = client.post("/api/v1/search", json={"limit": 2, "sort": "name", "descending": False}).json()
    assert first["total"] == 5 and len(first["items"]) == 2 and first["next_cursor"]
    second = client.post("/api/v1/search", json={"limit": 2, "sort": "name", "descending": False, "cursor": first["next_cursor"]}).json()
    assert second["total"] is None and {i["id"] for i in second["items"]}.isdisjoint({i["id"] for i in first["items"]})
    bad = client.post("/api/v1/search", json={"limit": 2, "sort": "size", "cursor": first["next_cursor"]})
    assert bad.status_code == 400
    facets = client.post("/api/v1/search/facets", json={}).json()
    assert {f["value"] for f in facets["platforms"]} == {"sd-webui", "comfyui", "invokeai"}
    assert client.get("/api/v1/search/stats").json()["total"] == 5
    assert len(client.get("/api/v1/search/random", params={"limit": 3}).json()["items"]) == 3
    similar = client.get(f"/api/v1/images/{first['items'][0]['id']}/similar", params={"by": "model"}).json()
    assert similar["items"]


def test_tags_flow(client, root, services):
    tag = client.post("/api/v1/tags", json={"name": "keep", "color": "#00ff00"}, headers=ORIGIN).json()
    image = services.index.record_by_path(root, f"{DAY}/00001-1234567890.png")
    r = client.post(f"/api/v1/tags/{tag['id']}/images", json={"image_ids": [image.id]}, headers=ORIGIN).json()
    assert r["changed"] == 1 and r["tag"]["count"] == 1
    assert [t["name"] for t in client.get(f"/api/v1/images/{image.id}/tags").json() if t["type"] == "custom"] == ["keep"]
    assert client.patch(f"/api/v1/tags/{tag['id']}", json={"name": "kept"}, headers=ORIGIN).json()["name"] == "kept"
    assert client.request("DELETE", f"/api/v1/tags/{tag['id']}/images", json={"image_ids": [image.id]}, headers=ORIGIN).json()["changed"] == 1
    platform = services.index.find_tag("sd-webui", "platform")
    assert client.delete(f"/api/v1/tags/{platform.id}", headers=ORIGIN).status_code == 400
    assert client.delete(f"/api/v1/tags/{tag['id']}", headers=ORIGIN).status_code == 204
    assert "prompt" in {t["type"] for t in client.get("/api/v1/tags").json()}


def test_upload_streams_and_indexes(client, root, services):
    data = (FIXTURES / "forge_txt2img.png").read_bytes()
    r = client.put("/api/v1/library/upload", params={"root_id": root, "path": DAY, "name": "dropped/up.png"}, content=data, headers=ORIGIN)
    assert r.status_code == 201, r.text
    assert r.json() == {"root_id": root, "path": f"{DAY}/dropped/up.png"}
    assert services.index.record_by_path(root, f"{DAY}/dropped/up.png").seed == 520469227
    again = client.put("/api/v1/library/upload", params={"root_id": root, "path": DAY, "name": "dropped/up.png"}, content=data, headers=ORIGIN)
    assert again.status_code == 409


def test_file_operations(client, root, services):
    r = client.post("/api/v1/library/folders", json={"root_id": root, "path": "outputs/txt2img-images", "name": "picked"}, headers=ORIGIN)
    assert r.status_code == 201
    moved = client.post(
        "/api/v1/library/move",
        json={"items": [{"root_id": root, "path": f"{DAY}/00001-1234567890.png"}], "dest_root_id": root, "dest_dir": "outputs/txt2img-images/picked"},
        headers=ORIGIN,
    ).json()
    assert moved["paths"][0]["path"] == "outputs/txt2img-images/picked/00001-1234567890.png"
    copied = client.post("/api/v1/library/copy", json={"items": moved["paths"], "dest_root_id": root, "dest_dir": DAY}, headers=ORIGIN).json()
    assert copied["paths"][0]["path"] == f"{DAY}/00001-1234567890.png"
    renamed = client.post("/api/v1/library/rename", json={"root_id": root, "path": copied["paths"][0]["path"], "new_name": "copy"}, headers=ORIGIN).json()
    assert renamed["paths"][0]["path"] == f"{DAY}/copy.png"
    assert client.post("/api/v1/library/delete", json={"items": renamed["paths"], "permanent": True}, headers=ORIGIN).status_code == 200
    zipped = client.post("/api/v1/library/zip", json={"items": moved["paths"], "name": "pick"}, headers=ORIGIN)
    assert zipped.status_code == 200 and zipped.headers["content-type"] == "application/zip" and zipped.content[:2] == b"PK"
    located = client.get("/api/v1/library/locate", params={"path": str(services.library.root_path(root) / DAY)}).json()
    assert located == {"root_id": root, "path": DAY}
    assert client.get("/api/v1/library/detect-layout", params={"path": str(services.library.root_path(root))}).json()["layout"] == "sd-webui"


def test_index_endpoints(client, root, services):
    status = client.post("/api/v1/index/scan", json={"root_id": root, "full": True}, headers=ORIGIN).json()
    assert status["queued"] == 1
    assert client.post("/api/v1/index/scan", json={"root_id": root, "full": True}, headers=ORIGIN).json()["code"] == "index_busy"
    assert client.post("/api/v1/index/cancel", headers=ORIGIN).json()["queued"] == 0
    summary = client.get("/api/v1/index/roots").json()
    assert summary[0]["images"] == 5
    assert client.get("/api/v1/index/status").json()["running"] is False


def test_open_is_local_only(app, root):
    with TestClient(app, base_url="http://localhost", client=("192.168.1.5", 5000)) as c:
        r = c.post("/api/v1/library/open", json={"root_id": root, "path": DAY}, headers=ORIGIN)
        assert r.status_code == 403 and r.json()["code"] == "not_local"
        assert c.get("/api/v1/app/meta").json()["local"] is False


def test_openapi_carries_the_events(app):
    schema = app.openapi()
    events = schema["components"]["schemas"]["ServerEvents"]["properties"]
    assert set(events) == {"scan_started", "scan_progress", "scan_completed", "scan_failed", "index_changed", "library_changed", "tags_changed", "import_progress"}
    assert all(op.get("operationId") for path in schema["paths"].values() for op in path.values())
