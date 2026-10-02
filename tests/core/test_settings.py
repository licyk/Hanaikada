import json

import pytest

from hanaikada.core.errors import ValidationError
from hanaikada.core.metadata.models import GenerationInfo
from hanaikada.core.record import PYDANTIC_V2
from hanaikada.core.settings import SettingsService


def test_defaults_and_save(tmp_path):
    s = SettingsService(data_dir=tmp_path, environ={})
    assert s.settings.server.host == "127.0.0.1"
    assert s.settings.server.port == 7867
    assert s.settings.index.image_extensions == [".png", ".jpg", ".jpeg", ".webp", ".avif", ".gif", ".jxl"]
    s.update({"server": {"port": 9000}, "index": {"watch_interval": 0}})
    again = SettingsService(data_dir=tmp_path, environ={})
    assert again.settings.server.port == 9000
    assert again.settings.index.watch_interval == 0


def test_view_hides_the_access_token(tmp_path):
    s = SettingsService(data_dir=tmp_path, environ={})
    s.update({"server": {"access_token": "secret-token"}})
    dumped = s.view().model_dump_json()
    assert "secret-token" not in dumped
    assert s.view().server.access_token_configured is True
    s.update({"server": {"access_token": None}})
    assert s.settings.server.access_token is None


def test_env_overrides_file_but_is_not_saved(tmp_path):
    s = SettingsService(data_dir=tmp_path, environ={"HANAIKADA_SERVER__PORT": "8123", "HANAIKADA_CONTENT__BLUR_TAGS": '["nsfw"]'})
    assert s.settings.server.port == 8123
    assert s.settings.content.blur_tags == ["nsfw"]
    s.update({"thumbnails": {"quality": 70}})
    assert "8123" not in s.path.read_text()
    assert s.view().env_overrides == ["HANAIKADA_CONTENT__BLUR_TAGS", "HANAIKADA_SERVER__PORT"]


def test_host_overrides_win_and_are_never_written(tmp_path):
    s = SettingsService(data_dir=tmp_path, environ={}, overrides={"index": {"scan_on_start": False}})
    s.update({"index": {"scan_on_start": True, "watch_interval": 5}})
    assert s.settings.index.scan_on_start is False
    assert s.settings.index.watch_interval == 5


def test_pinned_settings_are_named_in_the_view(tmp_path):
    s = SettingsService(data_dir=tmp_path, environ={}, overrides={"library": {"combined_view": True}, "server": {"access_token": "secret"}})
    view = s.view()
    assert view.pinned == ["library.combined_view", "server.access_token"]
    assert "secret" not in view.model_dump_json()
    assert SettingsService(data_dir=tmp_path / "other", environ={}).view().pinned == []


def test_invalid_values_rejected(tmp_path):
    s = SettingsService(data_dir=tmp_path, environ={})
    with pytest.raises(ValidationError):
        s.update({"server": {"port": 70000}})
    with pytest.raises(ValidationError):
        s.update({"paths": {"roots": [{"id": "x", "name": "x", "path": "/x", "layout": "nope"}]}})
    with pytest.raises(ValidationError):
        s.set_value("nope.nothing", "1")


def test_set_value_parses_json(tmp_path):
    s = SettingsService(data_dir=tmp_path, environ={})
    s.set_value("library.delete_to_trash", "false")
    s.set_value("content.blur_tags", '["nsfw", "gore"]')
    assert s.settings.library.delete_to_trash is False
    assert s.get_value("content.blur_tags") == ["nsfw", "gore"]


@pytest.mark.skipif(not PYDANTIC_V2, reason="Pydantic v1 has no plain serializers: big seeds stay numbers there")
def test_big_seeds_go_out_as_strings():
    assert json.loads(GenerationInfo(seed=2**53 - 1).model_dump_json())["seed"] == 2**53 - 1
    assert json.loads(GenerationInfo(seed=2**53).model_dump_json())["seed"] == str(2**53)
    assert GenerationInfo(seed=2**64 - 1).model_dump()["seed"] == 2**64 - 1
