"""Every parser over the real outputs on this machine (marker ``corpus``, deselected by default).

Run with ``python scripts/dev.py corpus``. The folders are the local WebUI, ComfyUI and InvokeAI
installs the reference documents were written from; a folder that does not exist is skipped.
"""

from pathlib import Path

import pytest

from hanaikada.core.metadata import MetadataService

HOME = Path.home()
CORPUS = {
    "sd-webui": HOME / "stable-diffusion-webui" / "core" / "outputs" / "txt2img-images",
    "comfyui": HOME / "ComfyUI" / "core" / "output",
    "invokeai": HOME / "InvokeAI" / "core" / "outputs" / "images",
}
# Files the references say carry no generation parameters: post-processing graphs, uploads.
NO_SAMPLER_OK = {"ComfyUI_0000"}

pytestmark = pytest.mark.corpus


@pytest.mark.parametrize("platform", sorted(CORPUS))
def test_every_file_parses(platform):
    folder = CORPUS[platform]
    if not folder.is_dir():
        pytest.skip(f"{folder} is not on this machine")
    service = MetadataService()
    files = sorted(p for p in folder.glob("*.png"))
    assert files
    parsed = {path.name: service.read(path) for path in files}
    assert {name: p.error for name, p in parsed.items() if p.error} == {}
    detected = [p for p in parsed.values() if p.info.platform != "none"]
    assert detected, "no file of the platform was recognised"
    assert all(p.info.platform == platform for p in detected)
    for name, p in parsed.items():
        if p.info.platform == "none" or any(name.startswith(prefix) for prefix in NO_SAMPLER_OK):
            continue
        assert p.info.prompt, name
        assert p.info.seed is not None, name
        assert p.info.model is not None, name
