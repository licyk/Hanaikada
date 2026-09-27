"""The A1111 infotext grammar and the sd-webui parser."""

import json

from hanaikada.core.metadata.containers import read_path
from hanaikada.core.metadata.infotext import extra_networks, looks_like_infotext, parse_infotext, parse_name_list, parse_unit, quote, split_size, unquote
from hanaikada.core.metadata.models import RawMetadata
from hanaikada.core.metadata.parsers.sd_webui import SdWebUIParser
from hanaikada.core.metadata.samplers import normalize_sampler, normalize_scheduler, split_invokeai_scheduler, split_webui_sampler
from tests.helpers import FIXTURES, INFOTEXT


def parse(text: str, key: str = "parameters"):
    return SdWebUIParser().parse(RawMetadata(chunks={key: text}, chunk_sources={key: "png:tEXt"}))


def test_layout_prompt_negative_params():
    parsed = parse_infotext(INFOTEXT)
    assert parsed.prompt == "1girl, solo, <lora:styleA:0.8>, (masterpiece:1.2)\ncherry blossoms, BREAK outdoors"
    assert parsed.negative_prompt == "lowres, bad anatomy"
    assert parsed.params["Steps"] == "28"
    assert parsed.params["Lora hashes"] == "styleA: 0123456789ab"


def test_quoted_values_with_commas_colons_and_escapes():
    line = 'Steps: 1, Sampler: Euler, Seed: 2, Note: "a, b: c \\"d\\"", Multi: "x\\ny"'
    params = parse_infotext("prompt\n" + line).params
    assert params["Note"] == 'a, b: c "d"'
    assert params["Multi"] == "x\ny"
    assert unquote(quote("a, b")) == "a, b"
    assert quote("plain") == "plain"


def test_last_line_with_fewer_than_three_pairs_is_prompt():
    parsed = parse_infotext("a prompt\nSteps: 20, Seed: 1")
    assert parsed.params == {}
    assert parsed.prompt == "a prompt\nSteps: 20, Seed: 1"


def test_multi_line_negative_prompt():
    parsed = parse_infotext("p1\np2\nNegative prompt: n1\nn2\nSteps: 1, Sampler: Euler, Seed: 3")
    assert parsed.prompt == "p1\np2"
    assert parsed.negative_prompt == "n1\nn2"


def test_trailing_lines_after_the_parameter_line():
    text = "a cat\nSteps: 20, Sampler: Euler, Seed: 1, Size: 512x512\nTemplate: a {cat|dog}\nNegative Template: bad"
    parsed = parse_infotext(text)
    assert parsed.prompt == "a cat"
    assert parsed.params["Seed"] == "1"
    assert parsed.trailing == {"Template": "a {cat|dog}", "Negative Template": "bad"}


def test_size_and_lists():
    assert split_size("1080x1920") == (1080, 1920)
    assert split_size("big") is None
    assert parse_name_list("a: 0x12, b: 34") == {"a": "0x12", "b": "34"}
    assert parse_unit("Module: canny, Model: cn [d14c016b], Weight: 1.0") == {"Module": "canny", "Model": "cn [d14c016b]", "Weight": "1.0"}


def test_extra_networks():
    nets = extra_networks("<lora:a:0.8>, <lora:b:0.5:1.0>, <lyco:c:te=0.3:unet=0.6>, <hypernet:d:1>")
    assert [(n.kind, n.name, n.te, n.unet) for n in nets] == [("lora", "a", 0.8, None), ("lora", "b", 0.5, 1.0), ("lyco", "c", 0.3, 0.6), ("hypernet", "d", 1.0, None)]


def test_shape_detection():
    assert looks_like_infotext(INFOTEXT)
    assert looks_like_infotext("prompt\nNegative prompt: x")
    assert not looks_like_infotext("Canon EOS 5D")
    assert not looks_like_infotext("")


def test_forge_fixture_maps_every_known_key():
    info = SdWebUIParser().parse(read_path(FIXTURES / "forge_txt2img.png"))
    assert info.platform == "sd-webui"
    assert info.platform_version == "f2.0.1v1.10.1-previous-669-gdfdcbab6"
    assert (info.seed, info.steps, info.cfg_scale, info.width, info.height) == (520469227, 20, 5.0, 1080, 1920)
    assert (info.sampler, info.scheduler, info.sampler_norm) == ("Euler a", "SGM Uniform", "euler_ancestral")
    assert info.model and (info.model.name, info.model.hash, info.model.hash_kind) == ("noobaiXLNAIXL_vPred10Version", "ea349eeae8", "sha256-10")
    assert [(lora.name, lora.weight, lora.hash) for lora in info.loras] == [("ill-xl-01-ogipote_3", 0.9, "0xc5d2ab0aab")]
    assert info.mode == "txt2img"
    assert info.extras["kohya_hrfix_block_number"] == "3"
    assert "<lora:ill-xl-01-ogipote_3:0.9>" in (info.prompt or "")
    assert info.sources == ["parameters"]


def test_hires_pass_takes_the_denoising_strength():
    info = parse(
        "p\nSteps: 20, Sampler: Euler a, CFG scale: 7, Seed: 1, Size: 512x768, Denoising strength: 0.4, Hires upscale: 2, Hires steps: 10, Hires upscaler: Latent, Hires sampler: Use same sampler"
    )
    assert info.denoise is None
    assert info.mode == "txt2img"
    hires = info.passes[0]
    assert (hires.kind, hires.denoise, hires.upscale, hires.steps, hires.upscaler, hires.width, hires.height, hires.sampler) == ("hires", 0.4, 2.0, 10, "Latent", 1024, 1536, None)


def test_old_infotext_sampler_undefined():
    info = SdWebUIParser().parse(RawMetadata(chunks={"parameters": "a cat\nSteps: 20, Sampler: Undefined, CFG scale: 7, Seed: 1, Size: 512x512"}))
    assert (info.sampler, info.scheduler, info.sampler_norm) == ("Euler", "Simple", "euler")


def test_old_hires_fix_first_pass_size():
    text = "a cat\nSteps: 20, Sampler: Euler a, CFG scale: 7, Seed: 1, Size: 1024x768, Denoising strength: 0.6, First pass size: 512x384"
    info = SdWebUIParser().parse(RawMetadata(chunks={"parameters": text}))
    assert (info.width, info.height, info.mode, info.denoise) == (512, 384, "txt2img", None)
    assert [(p.kind, p.width, p.height, p.denoise) for p in info.passes] == [("hires", 1024, 768, 0.6)]
    assert "First pass size" not in info.extras
    # 0x0: the WebUI chose about 512×512 pixels in the final aspect, in steps of 64.
    auto = SdWebUIParser().parse(RawMetadata(chunks={"parameters": text.replace("512x384", "0x0")}))
    assert (auto.width, auto.height, auto.passes[0].width) == (640, 448, 1024)


def test_img2img_and_inpaint_modes():
    assert parse("p\nSteps: 20, Sampler: Euler, Seed: 1, Denoising strength: 0.5").mode == "img2img"
    info = parse("p\nSteps: 20, Sampler: Euler, Seed: 1, Denoising strength: 0.5, Mask blur: 4, Inpaint area: Only masked")
    assert info.mode == "inpaint"
    assert info.denoise == 0.5
    assert info.extras["Mask blur"] == "4"


def test_hashes_json_vae_and_clip_skip_are_kept():
    hashes = quote(json.dumps({"model": "abcdef1234", "vae": "1111111111", "lora:foo": "222222222222"}))
    info = parse(f"p\nSteps: 20, Sampler: DPM++ 2M Karras, CFG scale: 7, Seed: 1, Model: m, VAE: vae-ft.safetensors, Clip skip: 2, Hashes: {hashes}")
    assert info.model and info.model.hash == "abcdef1234"
    assert info.vae and (info.vae.name, info.vae.hash) == ("vae-ft", "1111111111")
    assert info.clip_skip == 2
    assert (info.sampler, info.scheduler, info.sampler_norm) == ("DPM++ 2M", "Karras", "dpmpp_2m")
    assert [(lora.name, lora.hash) for lora in info.loras] == [("foo", "222222222222")]


def test_forge_modules_give_the_vae():
    info = parse("p\nSteps: 20, Sampler: Euler, Seed: 1, Module 1: ae.safetensors, Module 2: clip_l.safetensors, Distilled CFG Scale: 3.5")
    assert info.vae and info.vae.name == "ae"
    assert info.distilled_cfg == 3.5
    assert info.extras["Module 2"] == "clip_l.safetensors"


def test_controlnet_units():
    info = parse('p\nSteps: 20, Sampler: Euler, Seed: 1, ControlNet 0: "Module: canny, Model: control_v11p_sd15_canny [d14c016b], Weight: 1.0, Guidance Start: 0.0"')
    assert info.controls == [{"type": "controlnet", "index": 0, "module": "canny", "model": "control_v11p_sd15_canny [d14c016b]", "weight": "1.0", "guidance_start": "0.0"}]
    assert "ControlNet 0" not in info.extras


def test_refiner_and_postprocess_keys():
    info = parse("p\nSteps: 20, Sampler: Euler, Seed: 1, Refiner: sdxl_refiner [7440042bbd], Refiner switch at: 0.8, Postprocess upscaler: R-ESRGAN 4x+, Postprocess upscale by: 2")
    kinds = [(p.kind, p.model.name if p.model else p.upscaler) for p in info.passes]
    assert kinds == [("refiner", "sdxl_refiner"), ("upscale", "R-ESRGAN 4x+")]
    assert info.extras["Refiner switch at"] == "0.8"


def test_extras_tab_png_keeps_the_original_and_adds_an_upscale():
    raw = RawMetadata(chunks={"parameters": INFOTEXT, "postprocessing": "Postprocess upscale by: 4, Postprocess upscaler: R-ESRGAN 4x+"})
    info = SdWebUIParser().parse(raw)
    assert info.seed == 1234567890
    assert info.mode == "upscale"
    assert info.passes[-1].upscale == 4.0
    assert info.sources == ["parameters", "postprocessing"]


def test_extras_tab_jpeg_carries_only_the_postprocessing_text():
    raw = RawMetadata(chunks={"UserComment": "Postprocess upscale by: 2, Postprocess upscaler: 4x-UltraSharp"}, chunk_sources={"UserComment": "exif:UserComment"})
    parser = SdWebUIParser()
    assert parser.detect(raw)
    info = parser.parse(raw)
    assert info.mode == "upscale"
    assert info.prompt is None
    assert info.passes[0].upscaler == "4x-UltraSharp"


def test_camera_user_comment_is_not_an_infotext():
    assert not SdWebUIParser().detect(RawMetadata(chunks={"UserComment": "Holiday photo"}))


def test_sidecar_source_name():
    info = parse(INFOTEXT, key="sidecar:txt")
    assert info.sources == ["sidecar:txt"]
    assert info.seed == 1234567890


def test_sampler_vocabularies():
    assert normalize_sampler("Euler a") == "euler_ancestral"
    assert normalize_sampler("DPM++ 2M SDE") == "dpmpp_2m_sde"
    assert normalize_sampler("k_euler_ancestral") == "euler_ancestral"
    assert normalize_sampler("euler_a") == "euler_ancestral"
    assert normalize_sampler("Some New Sampler") == "some_new_sampler"
    assert normalize_scheduler("SGM Uniform") == "sgm_uniform"
    assert split_webui_sampler("DPM++ 2M SDE Karras") == ("DPM++ 2M SDE", "Karras")
    assert split_webui_sampler("Euler a") == ("Euler a", None)
    assert split_invokeai_scheduler("dpmpp_2m_k") == ("dpmpp_2m", "karras")
    assert split_invokeai_scheduler("kdpm_2_a_k") == ("kdpm_2_a", "karras")
    assert split_invokeai_scheduler("euler_a") == ("euler_a", None)
