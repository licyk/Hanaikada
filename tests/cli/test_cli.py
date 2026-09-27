import json
import logging

import pytest
from typer.testing import CliRunner

from hanaikada.cli.app import get_app
from hanaikada.logger import LOGGER_NAME
from tests.conftest import make_webui
from tests.helpers import FIXTURES

EXPECTED_TREE = {
    "config": {"get": None, "path": None, "set": None, "show": None},
    "copy": None,
    "delete": None,
    "env": None,
    "export": None,
    "info": None,
    "ls": None,
    "mkdir": None,
    "move": None,
    "rename": None,
    "root": {"add": None, "list": None, "remove": None},
    "scan": None,
    "search": None,
    "tag": {"add": None, "apply": None, "list": None, "remove": None, "show": None, "unapply": None},
    "thumbs": {"clear": None, "generate": None},
    "version": None,
    "webui": None,
}
DAY = "outputs/txt2img-images/2026-09-26"


def _tree(group):
    import typer

    click_group = typer.main.get_command(group) if not hasattr(group, "commands") else group
    out = {}
    for name, cmd in click_group.commands.items():
        out[name] = _tree(cmd) if hasattr(cmd, "commands") else None
    return out


@pytest.fixture
def runner(tmp_path, monkeypatch):
    monkeypatch.setenv("HANAIKADA_DATA_DIR", str(tmp_path / "data"))
    # --debug sets the application logger to DEBUG for the whole process; reset it so one test's
    # log lines cannot end up in another's captured output.
    logger = logging.getLogger(LOGGER_NAME)
    level = logger.level
    yield CliRunner()
    logger.setLevel(level)


@pytest.fixture
def indexed(runner, tmp_path):
    webui = make_webui(tmp_path / "webui")
    app = get_app()
    added = runner.invoke(app, ["root", "add", str(webui), "--json"])
    assert added.exit_code == 0, added.output
    root_id = json.loads(added.output)["id"]
    scanned = runner.invoke(app, ["scan", "--root", root_id, "--local"])
    assert scanned.exit_code == 0, scanned.output
    return root_id, webui


def test_command_tree_snapshot():
    assert _tree(get_app()) == EXPECTED_TREE


@pytest.mark.parametrize("args", [["--debug", "env"], ["env", "--debug"], ["root", "--debug", "list"], ["root", "list", "--debug"]])
def test_debug_option_everywhere(runner, args):
    result = runner.invoke(get_app(), args)
    assert result.exit_code == 0, result.output


def test_help_is_alphabetical(runner):
    out = runner.invoke(get_app(), ["--help"]).output
    names = [line.split()[0] for line in out.split("Commands:")[1].strip().splitlines() if line.startswith("  ") and not line.startswith("   ")]
    assert names == sorted(names)


def test_version_json(runner):
    data = json.loads(runner.invoke(get_app(), ["version", "--json"]).output)
    assert data["hanaikada"] and data["sqlite"]["version"]


def test_config_roundtrip_and_error_exit_code(runner):
    assert runner.invoke(get_app(), ["config", "set", "server.port", "8001"]).exit_code == 0
    assert json.loads(runner.invoke(get_app(), ["config", "get", "server.port"]).output) == 8001
    from hanaikada.core.errors import ValidationError

    result = runner.invoke(get_app(), ["config", "get", "nope"])
    assert isinstance(result.exception, ValidationError) and result.exception.exit_code == 4


def test_info_needs_no_data_directory(runner, tmp_path):
    result = runner.invoke(get_app(), ["info", str(FIXTURES / "forge_txt2img.png"), "--json"])
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["info"]["seed"] == 520469227 and data["raw"]["chunks"][0]["key"] == "parameters"
    assert not (tmp_path / "data").exists()
    table = runner.invoke(get_app(), ["info", str(FIXTURES / "comfyui_through_extras.png"), "--raw"])
    assert table.exit_code == 0 and "comfyui" in table.output and "workflow" in table.output


def test_info_json_equals_the_api(runner, services):
    from fastapi.testclient import TestClient

    from hanaikada.api.app import create_app

    path = FIXTURES / "invokeai_6.9.png"
    cli = json.loads(runner.invoke(get_app(), ["info", str(path), "--json"]).output)
    with TestClient(create_app(services, start_scanner=False, serve_ui=False), base_url="http://localhost") as client:
        api = client.post("/api/v1/images/parse", params={"name": path.name}, content=path.read_bytes()).json()
    cli["raw"]["sidecars"] = api["raw"]["sidecars"]
    assert cli == api


def test_scan_ls_search_and_tags(runner, indexed):
    root_id, webui = indexed
    app = get_app()
    listing = json.loads(runner.invoke(app, ["ls", f"{root_id}:{DAY}", "--json", "--sort", "name", "--asc"]).output)
    assert [f["name"] for f in listing["files"]] == ["00000-520469227.jpg", "00000-520469227.png", "00001-1234567890.png"]
    by_path = runner.invoke(app, ["ls", str(webui / DAY)])
    assert by_path.exit_code == 0 and f"{root_id}:{DAY} — 3 files" in by_path.output
    recursive = json.loads(runner.invoke(app, ["ls", f"{root_id}:outputs", "-r", "--json"]).output)
    assert len(recursive) == 5
    combined = json.loads(runner.invoke(app, ["ls", "--all-roots", "--json"]).output)
    assert [(f["root_id"], f["path"]) for f in combined["folders"]] == [(root_id, "outputs/txt2img-images"), (root_id, "outputs/extras-images")]
    table = runner.invoke(app, ["ls", "--all-roots"])
    assert table.exit_code == 0 and f"{root_id}:outputs/extras-images" in table.output
    assert runner.invoke(app, ["ls", "--all-roots", "-r"]).exit_code != 0
    found = json.loads(runner.invoke(app, ["search", "blossoms, BREAK", "--json"]).output)
    assert [i["name"] for i in found["items"]] == ["00001-1234567890.png"]
    assert json.loads(runner.invoke(app, ["search", "--platform", "comfyui", "--json"]).output)["total"] == 1
    assert runner.invoke(app, ["tag", "add", "picked"]).exit_code == 0
    applied = runner.invoke(app, ["tag", "apply", "picked", f"{root_id}:{DAY}/00001-1234567890.png", str(webui / DAY / "00000-520469227.png")])
    assert applied.exit_code == 0, applied.output
    tagged = json.loads(runner.invoke(app, ["search", "--tag", "picked", "--json"]).output)
    assert tagged["total"] == 2
    assert json.loads(runner.invoke(app, ["tag", "list", "--type", "custom", "--json"]).output)[0]["name"] in ("picked", "favorite")
    assert runner.invoke(app, ["tag", "unapply", "picked", f"{root_id}:{DAY}/00001-1234567890.png"]).exit_code == 0
    assert runner.invoke(app, ["tag", "remove", "picked"]).exit_code == 0


def test_file_commands(runner, indexed, tmp_path):
    root_id, webui = indexed
    app = get_app()
    assert runner.invoke(app, ["mkdir", f"{root_id}:outputs/txt2img-images/keep"]).exit_code == 0
    moved = runner.invoke(app, ["move", f"{root_id}:{DAY}/00001-1234567890.png", f"{root_id}:outputs/txt2img-images/keep", "--json"])
    assert moved.exit_code == 0, moved.output
    assert (webui / "outputs/txt2img-images/keep/00001-1234567890.png").is_file()
    assert runner.invoke(app, ["copy", f"{root_id}:outputs/txt2img-images/keep/00001-1234567890.png", f"{root_id}:{DAY}"]).exit_code == 0
    assert runner.invoke(app, ["rename", f"{root_id}:{DAY}/00001-1234567890.png", "again"]).exit_code == 0
    assert runner.invoke(app, ["delete", f"{root_id}:{DAY}/again.png", "--permanent", "--yes"]).exit_code == 0
    assert not (webui / DAY / "again.png").exists()
    out = tmp_path / "exported"
    assert runner.invoke(app, ["export", f"{root_id}:outputs/extras-images/00000.png", "--what", "workflow", "--to", str(out)]).exit_code == 0
    assert json.loads((out / "00000.workflow.json").read_text())["nodes"]
    assert runner.invoke(app, ["export", str(FIXTURES / "forge_txt2img.png"), "--what", "infotext", "--to", str(out)]).exit_code == 0
    assert (out / "forge_txt2img.txt").read_text().startswith("1girl")
    assert runner.invoke(app, ["export", str(FIXTURES / "forge_txt2img.png"), "--what", "workflow", "--to", str(out)]).exit_code == 1
    thumbs = runner.invoke(app, ["thumbs", "generate", "--root", root_id, "--size", "128"])
    assert thumbs.exit_code == 0 and "5 thumbnails ready" in thumbs.output


def test_path_outside_roots_is_not_found(runner, tmp_path):
    from hanaikada.core.errors import NotFoundError

    result = runner.invoke(get_app(), ["ls", str(tmp_path)])
    assert isinstance(result.exception, NotFoundError) and result.exception.exit_code == 2
    result = runner.invoke(get_app(), ["ls", "nope:x"])
    assert isinstance(result.exception, NotFoundError)


def test_invalid_root_layout_is_validated(runner, tmp_path):
    from pydantic import ValidationError

    result = runner.invoke(get_app(), ["root", "add", str(tmp_path), "--layout", "invalid"])
    assert isinstance(result.exception, ValidationError)


def test_logging_setup_does_not_duplicate_handlers(monkeypatch):
    from hanaikada.logger import setup_logging

    logger = logging.getLogger(LOGGER_NAME)
    monkeypatch.setattr(logger, "handlers", [])
    monkeypatch.setattr(logger, "level", logging.NOTSET)
    monkeypatch.setattr(logger, "propagate", True)
    setup_logging("INFO")
    setup_logging("DEBUG")
    assert len(logger.handlers) == 1
    assert logger.level == logging.DEBUG
