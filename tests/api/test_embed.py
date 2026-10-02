"""Embedding Hanaikada in another application: HanaikadaServer, locked roots, the route prefix, mounting."""

import socket
import urllib.error
import urllib.request
from contextlib import asynccontextmanager
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from hanaikada import HanaikadaServer, ImageRoot
from hanaikada.api.app import create_app, normalize_prefix
from hanaikada.core.context import build_services
from hanaikada.core.errors import ConflictError
from hanaikada.core.events.models import LibraryChangedEvent
from hanaikada.core.library.models import RootCreate, RootUpdate
from tests.conftest import make_webui


def get(url: str, timeout: float = 10.0) -> tuple[int, str]:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            return response.status, response.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()


@pytest.fixture
def webui(tmp_path: Path) -> Path:
    return make_webui(tmp_path / "stable-diffusion-webui")


def test_start_serves_scans_and_stops(tmp_path, webui):
    server = HanaikadaServer(data_dir=tmp_path / "data", image_roots=[ImageRoot(webui, name="Forge")], port=0)
    url = server.start()
    try:
        assert url.startswith("http://127.0.0.1:") and server.running
        status, body = get(f"{url}/api/v1/library/roots")
        assert status == 200 and '"layout":"sd-webui"' in body.replace(" ", "") and '"name":"Forge"' in body.replace(" ", "")
        # The server's lifespan starts the scanner, which indexes the seeded root.
        assert server.services is not None and server.services.index.wait_idle(20)
        assert server.services.index.roots_summary()[0].images == 5
    finally:
        server.stop()
    assert not server.running


def test_stop_releases_the_port_and_is_repeatable(tmp_path):
    server = HanaikadaServer(data_dir=tmp_path / "data", port=0)
    server.start()
    port = server.port
    server.stop()
    server.stop()
    with pytest.raises(RuntimeError):
        _ = server.url
    with socket.socket() as s:
        s.bind(("127.0.0.1", port))


def test_a_taken_port_moves_up_unless_strict(tmp_path):
    with socket.socket() as taken:
        taken.bind(("127.0.0.1", 0))
        taken.listen()
        port = taken.getsockname()[1]
        moved = HanaikadaServer(data_dir=tmp_path / "a", port=port)
        try:
            moved.start()
            assert moved.port != port
        finally:
            moved.stop()
        strict = HanaikadaServer(data_dir=tmp_path / "b", port=port, strict_port=True)
        with pytest.raises(Exception, match="strict|unavailable"):
            strict.start()
        strict.stop()


def test_pinned_settings_and_settings_path(tmp_path):
    config = tmp_path / "host" / "hanaikada.toml"
    config.parent.mkdir()
    with HanaikadaServer(data_dir=tmp_path / "data", settings_path=config, port=0, settings={"index": {"watch_interval": 0}}) as server:
        services = server.services
        assert services is not None
        services.settings.update({"index": {"watch_interval": 60, "prompt_tag_min_count": 3}})
        assert services.settings.settings.index.watch_interval == 0
        assert services.settings.settings.index.prompt_tag_min_count == 3
        assert config.is_file() and (tmp_path / "data" / "hanaikada.db").is_file()


@pytest.mark.parametrize("value", [True, False])
def test_combined_view_can_be_pinned(tmp_path, value):
    server = HanaikadaServer(data_dir=tmp_path / "data", port=0, combined_view=value, settings={"library": {"show_all_files": True}})
    services = server._build()
    try:
        services.settings.update({"library": {"combined_view": not value}})
        assert services.settings.settings.library.combined_view is value
        # Pinning it keeps the host's other library settings.
        assert services.settings.settings.library.show_all_files is True
        assert "library.combined_view" in services.settings.view().pinned
    finally:
        services.close()


def test_combined_view_is_left_to_the_user_by_default(tmp_path):
    services = HanaikadaServer(data_dir=tmp_path / "data", port=0)._build()
    try:
        assert services.settings.settings.library.combined_view is False
        assert "library.combined_view" not in services.settings.view().pinned
        services.settings.update({"library": {"combined_view": True}})
        assert services.settings.settings.library.combined_view is True
    finally:
        services.close()


def test_generic_folder_names_take_the_parent_name(tmp_path):
    core = tmp_path / "ComfyUI-portable" / "core"
    core.mkdir(parents=True)
    assert ImageRoot(core).to_settings()["name"] == "ComfyUI-portable"
    services = build_services(data_dir=tmp_path / "data", environ={})
    try:
        assert services.library.add_root(RootCreate(path=str(core))).name == "ComfyUI-portable"
    finally:
        services.close()


def test_locked_roots_cannot_be_changed(tmp_path, webui):
    with HanaikadaServer(data_dir=tmp_path / "data", image_roots=[ImageRoot(webui, layout="sd-webui")], lock_image_roots=True, port=0) as server:
        library = server.services.library
        root_id = library.list_roots()[0].id
        for call in (
            lambda: library.add_root(RootCreate(path=str(tmp_path), layout="custom")),
            lambda: library.update_root(root_id, RootUpdate(name="other")),
            lambda: library.remove_root(root_id),
        ):
            with pytest.raises(ConflictError, match="fixed by the application"):
                call()
        assert '"roots_locked":true' in get(f"{server.url}/api/v1/app/meta")[1].replace(" ", "")
        assert get(f"{server.url}/api/v1/library/roots/{root_id}/entries?path=outputs")[0] == 200


@pytest.mark.parametrize(("given", "expected"), [(None, ""), ("", ""), ("/images", "/images"), ("images", "/images"), ("/images/", "/images"), ("a/b", "/a/b")])
def test_prefix_is_normalized(given, expected):
    assert normalize_prefix(given) == expected


def test_everything_moves_under_the_prefix(tmp_path):
    services = build_services(data_dir=tmp_path / "data", environ={})
    app = create_app(services, bound_host="127.0.0.1", start_scanner=False, serve_ui=False, api_prefix="/images")
    try:
        with TestClient(app, base_url="http://localhost") as client:
            assert client.get("/images/api/v1/app/health").status_code == 200
            assert client.get("/images/api/v1/app/meta").json()["api_prefix"] == "/images"
            reply = client.get("/images/ws/socket.io/", params={"EIO": "4", "transport": "polling"})
            assert reply.status_code == 200 and reply.text.startswith("0{")
            assert client.get("/api/v1/app/health").status_code == 404
    finally:
        services.close()


@pytest.mark.parametrize("mount,prefix", [("", "/images"), ("/host", ""), ("/host", "/images")])
def test_mounted_api_security_and_socket(tmp_path, mount, prefix):
    services = build_services(data_dir=tmp_path / "data", environ={})
    services.settings.update({"server": {"access_token": "secret"}})
    child = create_app(services, bound_host="localhost", api_prefix=prefix, start_scanner=False, serve_ui=False)

    @asynccontextmanager
    async def lifespan(_app):
        async with child.router.lifespan_context(child):
            yield

    parent = FastAPI(lifespan=lifespan)
    parent.mount(mount or "/", child)
    base = mount + prefix
    try:
        with TestClient(parent, base_url="http://localhost") as client:
            assert client.get(f"{base}/api/v1/app/health").status_code == 200
            assert client.get(f"{base}/api/v1/settings").status_code == 401
            headers = {"Authorization": "Bearer secret"}
            assert client.get(f"{base}/api/v1/settings", headers=headers).status_code == 200
            assert client.patch(f"{base}/api/v1/settings", json={}, headers={**headers, "Origin": "https://elsewhere.example"}).status_code == 403
            with client.websocket_connect(f"ws://localhost{base}/ws/socket.io/?EIO=4&transport=websocket", headers={**headers, "Upgrade": "websocket"}) as ws:
                assert ws.receive_text().startswith('0{"sid":')
                ws.send_text("40")
                assert ws.receive_text().startswith("40")
                services.events.publish(LibraryChangedEvent(root_id="r", rel_path="day"))
                message = ws.receive_text()
                assert message.startswith('42["library_changed",') and '"root_id":"r"' in message
    finally:
        services.close()


def test_mounted_ui_is_served(tmp_path, monkeypatch):
    from hanaikada.api import app as app_module

    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text('<script src="./assets/app.js"></script>')
    (dist / "assets" / "app.js").write_text("window.loaded = true;")
    monkeypatch.setattr(app_module, "web_dist_dir", lambda: dist)
    services = build_services(data_dir=tmp_path / "data", environ={})
    try:
        app = create_app(services, bound_host="127.0.0.1", start_scanner=False)
        with TestClient(app, base_url="http://localhost") as client:
            index = client.get("/", headers={"accept": "text/html"})
            assert index.text.startswith("<script") and index.headers["cache-control"] == "no-cache"
            asset = client.get("/assets/app.js")
            assert asset.text == "window.loaded = true;" and "immutable" in asset.headers["cache-control"]
            assert client.get("/some/deep/link", headers={"accept": "text/html"}).text.startswith("<script")
            assert client.get("/missing.js").status_code == 404
    finally:
        services.close()
