"""How each layout maps a root to output folders."""

import json

from hanaikada.core.library.layouts import detect_layout, is_ignored_name, plan_for


def test_webui_config_with_relative_and_absolute_outdirs(tmp_path):
    root = tmp_path / "webui"
    (root / "outputs" / "txt2img-images").mkdir(parents=True)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (root / "my-saves").mkdir()
    config = {"outdir_txt2img_samples": "outputs/txt2img-images", "outdir_img2img_samples": str(elsewhere), "outdir_save": str(root / "my-saves")}
    (root / "config.json").write_text(json.dumps(config))
    plan = plan_for("sd-webui", root)
    assert [(o.rel, o.label) for o in plan.outputs] == [("outputs/txt2img-images", "txt2img"), ("my-saves", "saved")]
    assert plan.dir_visible("outputs") and plan.dir_visible("outputs/txt2img-images/2026-09-26")
    assert not plan.dir_visible("extensions") and not plan.dir_visible("models")
    assert not plan.dir_indexed("outputs")
    assert plan.dir_indexed("outputs/txt2img-images/2026-09-26")
    assert not plan.file_visible("log.csv")


def test_webui_missing_keys_fall_back_to_the_install_defaults(tmp_path):
    root = tmp_path / "forge-classic"
    for sub in ("txt2img-images", "img2img-images"):
        (root / "output" / sub).mkdir(parents=True)
    (root / "config.json").write_text(json.dumps({"outdir_txt2img_samples": ""}))
    assert [o.rel for o in plan_for("sd-webui", root).outputs] == ["output/txt2img-images", "output/img2img-images"]


def test_webui_without_config(tmp_path):
    root = tmp_path / "webui"
    (root / "outputs" / "txt2img-images").mkdir(parents=True)
    assert [o.rel for o in plan_for("sd-webui", root).outputs] == ["outputs"]
    bare = tmp_path / "just-images"
    bare.mkdir()
    assert [o.rel for o in plan_for("sd-webui", bare).outputs] == [""]
    only_output = tmp_path / "classic"
    (only_output / "output").mkdir(parents=True)
    assert [o.rel for o in plan_for("sd-webui", only_output).outputs] == ["output"]


def test_comfyui_temp_toggle(tmp_path):
    root = tmp_path / "ComfyUI"
    for sub in ("output", "temp", "input", "models", "custom_nodes"):
        (root / sub).mkdir(parents=True)
    plan = plan_for("comfyui", root)
    assert [o.rel for o in plan.outputs] == ["output"]
    assert not plan.dir_visible("temp") and not plan.dir_visible("input")
    with_temp = plan_for("comfyui", root, include_comfyui_temp=True)
    assert [o.rel for o in with_temp.outputs] == ["output", "temp"]
    assert [o.rel for o in plan_for("comfyui", root / "output").outputs] == [""]


def test_invokeai_thumbnails_are_ignored(tmp_path):
    root = tmp_path / "invokeai"
    (root / "outputs" / "images" / "thumbnails").mkdir(parents=True)
    (root / "databases").mkdir()
    (root / "databases" / "invokeai.db").write_bytes(b"")
    (root / "invokeai.yaml").write_text("")
    plan = plan_for("invokeai", root)
    assert [o.rel for o in plan.outputs] == ["outputs/images"]
    assert not plan.dir_visible("outputs/images/thumbnails")
    assert plan.thumbnail_dirs == {"outputs/images": "outputs/images/thumbnails"}
    assert plan.invokeai_db == root / "databases" / "invokeai.db"
    # A root at the images folder itself finds the database two levels up.
    images = plan_for("invokeai", root / "outputs" / "images")
    assert [o.rel for o in images.outputs] == [""]
    assert images.invokeai_db == root / "databases" / "invokeai.db"
    assert not images.dir_visible("thumbnails")


def test_detection(tmp_path):
    webui = tmp_path / "a"
    webui.mkdir()
    (webui / "config.json").write_text(json.dumps({"outdir_txt2img_samples": "outputs/txt2img-images"}))
    comfy = tmp_path / "b"
    comfy.mkdir()
    (comfy / "main.py").write_text("")
    (comfy / "folder_paths.py").write_text("")
    invoke = tmp_path / "c"
    invoke.mkdir()
    (invoke / "invokeai.yaml").write_text("")
    plain = tmp_path / "d"
    plain.mkdir()
    assert [detect_layout(p)[0] for p in (webui, comfy, invoke, plain)] == ["sd-webui", "comfyui", "invokeai", "custom"]


def test_ignored_names():
    assert all(is_ignored_name(n) for n in (".hidden", "a.tmp", "b.part", "c.incomplete", "Thumbs.db"))
    assert not is_ignored_name("image.png")
