import json
import shutil
from pathlib import Path

import pytest

from hanaikada.core.context import Services, build_services
from hanaikada.core.library.models import RootCreate
from tests.helpers import FIXTURES, INFOTEXT, write_png


@pytest.fixture
def services(tmp_path: Path):
    s = build_services(data_dir=tmp_path / "data", environ={})
    yield s
    s.close()


def make_webui(base: Path) -> Path:
    """A WebUI install with config.json and a few outputs of every platform."""
    base.mkdir(parents=True, exist_ok=True)
    (base / "config.json").write_text(
        json.dumps({"outdir_txt2img_samples": "outputs/txt2img-images", "outdir_extras_samples": "outputs/extras-images", "outdir_save": "log/images"})
    )
    (base / "models" / "Lora").mkdir(parents=True)
    (base / "extensions" / "x").mkdir(parents=True)
    write_png(base / "extensions" / "x" / "preview.png", {"parameters": INFOTEXT})
    day = base / "outputs" / "txt2img-images" / "2026-09-26"
    day.mkdir(parents=True)
    shutil.copy(FIXTURES / "forge_txt2img.png", day / "00000-520469227.png")
    shutil.copy(FIXTURES / "forge_txt2img.jpg", day / "00000-520469227.jpg")
    write_png(day / "00001-1234567890.png", {"parameters": INFOTEXT})
    extras = base / "outputs" / "extras-images"
    extras.mkdir(parents=True)
    shutil.copy(FIXTURES / "comfyui_through_extras.png", extras / "00000.png")
    shutil.copy(FIXTURES / "invokeai_6.9.png", extras / "invoke.png")
    return base


@pytest.fixture
def webui_dir(tmp_path: Path) -> Path:
    return make_webui(tmp_path / "webui")


@pytest.fixture
def webui_root(services: Services, webui_dir: Path) -> str:
    return services.library.add_root(RootCreate(name="webui", path=str(webui_dir), layout="sd-webui")).id


@pytest.fixture
def scanned(services: Services, webui_root: str) -> str:
    from hanaikada.core.index.models import ScanRequest

    services.index.scan_now(ScanRequest(root_id=webui_root))
    return webui_root
