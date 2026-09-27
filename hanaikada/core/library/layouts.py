"""Layouts: how a root maps to output folders, what to call them, and what to leave out.

A root is a folder plus a layout. ``sd-webui``, ``comfyui`` and ``invokeai`` roots may point at the
installation folder or at an output folder inside it; either way the layout works out which
folders hold generated images (the *output folders*). Only those, their ancestors and their
descendants are browsed and indexed, so an install root does not list ``extensions/`` or
``models/``. A ``custom`` root is one output folder: itself.
"""

import json
import logging
import os
from dataclasses import dataclass
from fnmatch import fnmatch
from pathlib import Path

logger = logging.getLogger(__name__)

IGNORED_PATTERNS = ("*.tmp", "*.part", "*.incomplete", "Thumbs.db", "desktop.ini", ".DS_Store")

# The WebUI's output options (modules/shared_options.py) and the label each folder gets.
WEBUI_OUTDIRS = {
    "outdir_txt2img_samples": ("txt2img-images", "txt2img"),
    "outdir_img2img_samples": ("img2img-images", "img2img"),
    "outdir_extras_samples": ("extras-images", "extras"),
    "outdir_txt2img_grids": ("txt2img-grids", "txt2img-grids"),
    "outdir_img2img_grids": ("img2img-grids", "img2img-grids"),
    "outdir_save": ("images", "saved"),
    "outdir_init_images": ("init-images", "init-images"),
    "outdir_videos": ("videos", "videos"),
}


@dataclass(frozen=True)
class OutputFolder:
    rel: str
    """Relative to the root, POSIX; ``""`` is the root itself."""
    label: str | None = None


@dataclass
class LayoutPlan:
    """What a layout makes of one root folder, computed once per root and settings."""

    layout: str
    outputs: list[OutputFolder]
    ignored_dirs: set[str]
    """Folders (relative to the root) hidden with everything below them."""
    thumbnail_dirs: dict[str, str]
    """InvokeAI: output folder → its ``thumbnails`` folder, both relative to the root."""
    invokeai_db: Path | None = None
    hidden_files: tuple[str, ...] = ()

    def label(self, rel_dir: str) -> str | None:
        for out in self.outputs:
            if out.rel == rel_dir:
                return out.label
        return None

    def output_of(self, rel_dir: str) -> OutputFolder | None:
        """The output folder a folder lies in, if any."""
        best: OutputFolder | None = None
        for out in self.outputs:
            if (out.rel == "" or rel_dir == out.rel or rel_dir.startswith(out.rel + "/")) and (best is None or len(out.rel) > len(best.rel)):
                best = out
        return best

    def is_ignored_dir(self, rel_dir: str) -> bool:
        return any(rel_dir == d or rel_dir.startswith(d + "/") for d in self.ignored_dirs)

    def dir_visible(self, rel_dir: str) -> bool:
        """Whether a folder is browsed: an output folder, inside one, or on the way to one."""
        if rel_dir == "":
            return True
        if self.is_ignored_dir(rel_dir) or any(part.startswith(".") for part in rel_dir.split("/")):
            return False
        for out in self.outputs:
            if out.rel == "" or rel_dir == out.rel or rel_dir.startswith(out.rel + "/") or out.rel.startswith(rel_dir + "/"):
                return True
        return False

    def dir_indexed(self, rel_dir: str) -> bool:
        return self.dir_visible(rel_dir) and self.output_of(rel_dir) is not None

    def file_visible(self, name: str) -> bool:
        return not is_ignored_name(name) and name not in self.hidden_files


def is_ignored_name(name: str) -> bool:
    """Dot entries and temporary files, hidden in every layout."""
    return name.startswith(".") or any(fnmatch(name, pattern) for pattern in IGNORED_PATTERNS)


def _rel_inside(root: Path, value: str, base: Path) -> str | None:
    """A configured folder relative to the root, or None when it lies outside it."""
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = base / path
    try:
        rel = Path(os.path.normpath(path)).relative_to(Path(os.path.normpath(root)))
    except ValueError:
        return None
    text = rel.as_posix()
    return "" if text == "." else text


def _webui_plan(root: Path) -> LayoutPlan:
    config_path = root / "config.json"
    config: dict[str, object] = {}
    if config_path.is_file():
        try:
            loaded = json.loads(config_path.read_text(encoding="utf-8"))
            config = loaded if isinstance(loaded, dict) else {}
        except (OSError, ValueError) as e:
            logger.warning("Cannot read %s: %s", config_path, e)
    if config_path.is_file():
        # Upstream and Forge default to outputs/, Forge Classic to output/.
        default_base = "output" if (root / "output").is_dir() and not (root / "outputs").is_dir() else "outputs"
        outputs: list[OutputFolder] = []
        seen: set[str] = set()
        common = config.get("outdir_samples")
        for key, (sub, label) in WEBUI_OUTDIRS.items():
            value = config.get(key)
            if isinstance(common, str) and common and key not in ("outdir_save", "outdir_init_images", "outdir_videos"):
                value = common
            if not isinstance(value, str) or not value:
                value = "log/images" if key == "outdir_save" and not (root / f"{default_base}/images").is_dir() and (root / "log/images").is_dir() else f"{default_base}/{sub}"
            rel = _rel_inside(root, value, root)
            if rel is None:
                logger.info("%s = %s lies outside the root %s; add it as a root of its own to browse it", key, value, root)
                continue
            if rel not in seen and (root / rel).is_dir():
                seen.add(rel)
                outputs.append(OutputFolder(rel, label))
        grids = config.get("outdir_grids")
        if isinstance(grids, str) and grids:
            rel = _rel_inside(root, grids, root)
            if rel is not None and rel not in seen and (root / rel).is_dir():
                outputs.append(OutputFolder(rel, "grids"))
        if not outputs:
            for base in ("outputs", "output"):
                if (root / base).is_dir():
                    outputs.append(OutputFolder(base, None))
                    break
    else:
        outputs = []
        for base in ("outputs", "output"):
            if (root / base).is_dir():
                outputs.append(OutputFolder(base, None))
                break
        if not outputs:
            outputs = [OutputFolder("", None)]
    # A root pointing at an outputs folder: label the WebUI's own subfolders.
    labelled: list[OutputFolder] = []
    for out in outputs:
        if out.label is None:
            label = next((lab for sub, lab in WEBUI_OUTDIRS.values() if out.rel.rsplit("/", 1)[-1] == sub), None)
            labelled.append(OutputFolder(out.rel, label))
        else:
            labelled.append(out)
    return LayoutPlan("sd-webui", labelled, set(), {}, hidden_files=("log.csv",))


def _comfyui_plan(root: Path, include_temp: bool) -> LayoutPlan:
    ignored = {"input", "user", "models", "custom_nodes"}
    if (root / "output").is_dir():
        outputs = [OutputFolder("output", "output")]
        if include_temp and (root / "temp").is_dir():
            outputs.append(OutputFolder("temp", "temp"))
        else:
            ignored.add("temp")
    else:
        outputs = [OutputFolder("", "output")]
    return LayoutPlan("comfyui", outputs, ignored, {})


def _invokeai_plan(root: Path) -> LayoutPlan:
    if (root / "outputs" / "images").is_dir():
        images, install = "outputs/images", root
    elif (root / "images").is_dir() and not (root / "invokeai.yaml").is_file():
        images, install = "images", root.parent
    else:
        images, install = "", root.parent.parent
    thumbs = f"{images}/thumbnails" if images else "thumbnails"
    ignored = {thumbs}
    if images.startswith("outputs/"):
        ignored.add("outputs/models")
    db = install / "databases" / "invokeai.db"
    return LayoutPlan("invokeai", [OutputFolder(images, "images")], ignored, {images: thumbs}, invokeai_db=db if db.is_file() else None)


def plan_for(layout: str, root: Path, include_comfyui_temp: bool = False) -> LayoutPlan:
    if layout == "sd-webui":
        return _webui_plan(root)
    if layout == "comfyui":
        return _comfyui_plan(root, include_comfyui_temp)
    if layout == "invokeai":
        return _invokeai_plan(root)
    return LayoutPlan("custom", [OutputFolder("", None)], set(), {})


def detect_layout(root: Path) -> tuple[str, str]:
    """Suggest a layout for a folder, with the reason. Falls back to ``custom``."""
    config = root / "config.json"
    if config.is_file():
        try:
            data = json.loads(config.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = None
        if isinstance(data, dict) and "outdir_txt2img_samples" in data:
            return "sd-webui", "config.json has outdir_txt2img_samples"
    if (root / "invokeai.yaml").is_file():
        return "invokeai", "invokeai.yaml found"
    if (root / "main.py").is_file() and (root / "folder_paths.py").is_file():
        return "comfyui", "main.py and folder_paths.py found"
    if (root / "webui.py").is_file() and (root / "modules").is_dir():
        return "sd-webui", "webui.py and modules/ found"
    if (root / "outputs" / "images").is_dir() and (root / "outputs" / "images" / "thumbnails").is_dir():
        return "invokeai", "outputs/images/thumbnails found"
    if root.name in ("txt2img-images", "img2img-images", "extras-images") or any((root / n).is_dir() for n in ("txt2img-images", "img2img-images")):
        return "sd-webui", "WebUI output folders found"
    return "custom", "no known installation found"
