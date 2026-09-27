"""The ComfyUI graph walker: real graphs and synthetic ones for each shape the plan lists."""

import json

import pytest

from hanaikada.core.metadata.containers import read_path
from hanaikada.core.metadata.models import RawMetadata
from hanaikada.core.metadata.parsers.comfyui import ComfyUIParser, parse_graph, workflow_to_prompt
from hanaikada.core.record import PYDANTIC_V2
from tests.helpers import FIXTURES


def node(cls: str, **inputs):
    return {"class_type": cls, "inputs": inputs}


def base_graph(**sampler_overrides):
    graph = {
        "4": node("CheckpointLoaderSimple", ckpt_name="sdxl/base.safetensors"),
        "5": node("EmptyLatentImage", width=1024, height=1024, batch_size=1),
        "6": node("CLIPTextEncode", text="a cat", clip=["4", 1]),
        "7": node("CLIPTextEncode", text="blurry", clip=["4", 1]),
        "3": node(
            "KSampler",
            seed=42,
            steps=25,
            cfg=7.0,
            sampler_name="dpmpp_2m",
            scheduler="karras",
            denoise=1.0,
            model=["4", 0],
            positive=["6", 0],
            negative=["7", 0],
            latent_image=["5", 0],
        ),
        "8": node("VAEDecode", samples=["3", 0], vae=["4", 2]),
        "9": node("SaveImage", filename_prefix="ComfyUI", images=["8", 0]),
    }
    graph["3"]["inputs"].update(sampler_overrides)
    return graph


def test_real_txt2img():
    info = ComfyUIParser().parse(read_path(FIXTURES / "2026-05-10_19-05-35_00001_.png"), "2026-05-10_19-05-35_00001_.png")
    assert info.platform == "comfyui"
    assert (info.seed, info.steps, info.cfg_scale, info.sampler, info.scheduler, info.sampler_norm) == (
        399393160470141,
        20,
        5.0,
        "euler_ancestral",
        "sgm_uniform",
        "euler_ancestral",
    )
    assert (info.width, info.height, info.mode) == (1080, 1920, "txt2img")
    assert info.prompt and info.prompt.startswith("1girl,solo,cherry blossoms")
    assert info.negative_prompt and info.negative_prompt.startswith("tree,, low quality")
    assert info.model and (info.model.name, info.model.path) == ("noobaiXLNAIXL_vPred10Version", "noobaiXLNAIXL_vPred10Version.safetensors")
    assert [(lora.name, lora.weight, lora.weight_clip) for lora in info.loras] == [("ill-xl-01-MELT0209_1-000038", 1.0, 1.0)]
    assert info.extras["filename_prefix"] == "2026-05-10_19-05-35"
    # The pass-through PatchModelAddDownscale node is kept as extras, not lost.
    assert info.extras["PatchModelAddDownscale#18.block_number"] == 3
    assert info.sources == ["prompt", "workflow"]


def test_real_custom_node_workflow_through_the_extras_tab():
    info = ComfyUIParser().parse(read_path(FIXTURES / "comfyui_through_extras.png"), "00000.png")
    assert info.platform == "comfyui"
    assert (info.seed, info.steps, info.width, info.height) == (26084, 28, 1536, 1024)  # seed and size arrive by link
    assert info.prompt and info.prompt.startswith("licyk, 1girl")
    assert info.negative_prompt and info.negative_prompt.startswith("jpeg, signature")
    assert info.model and info.model.name == "anima-base-v1.0"
    assert info.vae and info.vae.name == "qwen_image_vae"
    assert [p.kind for p in info.passes] == ["hires", "hires", "sampler", "upscale"]
    assert info.passes[0].steps == 16  # through a MathExpression node
    assert info.passes[0].upscaler == "2x-AnimeSharpV4_Fast_RCAN_PU"
    assert "postprocessing" in info.sources
    assert any(lora.name == "anima_face_2-16" for lora in info.loras)


def test_graph_without_a_sampler_joins_every_encoder():
    info = ComfyUIParser().parse(read_path(FIXTURES / "ComfyUI_00001_.png"), "ComfyUI_00001_.png")
    assert info.warnings == ["no sampler node found"]
    assert info.prompt is None
    graph = {"1": node("CLIPTextEncode", text="one"), "2": node("CLIPTextEncode", text="two")}
    info = parse_graph(graph)
    assert info.prompt == "one\ntwo"
    assert info.prompts == ["one", "two"]


def test_basic_ksampler():
    info = parse_graph(base_graph())
    assert (info.seed, info.steps, info.cfg_scale, info.sampler_norm, info.scheduler) == (42, 25, 7.0, "dpmpp_2m", "karras")
    assert (info.prompt, info.negative_prompt, info.width, info.height, info.mode) == ("a cat", "blurry", 1024, 1024, "txt2img")
    assert info.model and info.model.name == "base"
    assert info.vae is None  # the checkpoint's own VAE
    assert info.denoise is None


def test_ksampler_advanced_hires_chain():
    graph = base_graph()
    graph["3"] = node(
        "KSamplerAdvanced",
        add_noise="enable",
        noise_seed=7,
        steps=20,
        cfg=6.0,
        sampler_name="euler",
        scheduler="normal",
        start_at_step=0,
        end_at_step=20,
        model=["4", 0],
        positive=["6", 0],
        negative=["7", 0],
        latent_image=["5", 0],
    )
    graph["10"] = node("LatentUpscaleBy", upscale_method="nearest-exact", scale_by=1.5, samples=["3", 0])
    graph["11"] = node(
        "KSamplerAdvanced",
        add_noise="enable",
        noise_seed=7,
        steps=12,
        cfg=6.0,
        sampler_name="euler",
        scheduler="normal",
        start_at_step=6,
        end_at_step=12,
        model=["4", 0],
        positive=["6", 0],
        negative=["7", 0],
        latent_image=["10", 0],
    )
    graph["8"]["inputs"]["samples"] = ["11", 0]
    info = parse_graph(graph)
    assert info.seed == 7 and info.steps == 20
    assert len(info.passes) == 1
    hires = info.passes[0]
    assert (hires.kind, hires.steps, hires.upscaler, hires.upscale) == ("hires", 12, "nearest-exact", 1.5)
    assert info.extras["KSamplerAdvanced#3.start_at_step"] == 0


def test_sampler_custom_advanced_with_flux_guidance():
    graph = {
        "1": node("UNETLoader", unet_name="flux1-dev.safetensors", weight_dtype="fp8_e4m3fn"),
        "2": node("DualCLIPLoader", clip_name1="t5xxl.safetensors", clip_name2="clip_l.safetensors", type="flux"),
        "3": node("VAELoader", vae_name="ae.safetensors"),
        "4": node("CLIPTextEncode", text="a fox in snow", clip=["2", 0]),
        "5": node("FluxGuidance", guidance=3.5, conditioning=["4", 0]),
        "6": node("BasicGuider", model=["1", 0], conditioning=["5", 0]),
        "7": node("RandomNoise", noise_seed=1234),
        "8": node("KSamplerSelect", sampler_name="euler"),
        "9": node("BasicScheduler", scheduler="simple", steps=28, denoise=1.0, model=["1", 0]),
        "10": node("EmptySD3LatentImage", width=896, height=1152, batch_size=1),
        "11": node("SamplerCustomAdvanced", noise=["7", 0], guider=["6", 0], sampler=["8", 0], sigmas=["9", 0], latent_image=["10", 0]),
        "12": node("VAEDecode", samples=["11", 0], vae=["3", 0]),
        "13": node("SaveImage", filename_prefix="flux/img", images=["12", 0]),
    }
    info = parse_graph(graph, "img_00001_.png")
    assert (info.seed, info.steps, info.sampler, info.scheduler, info.distilled_cfg, info.cfg_scale) == (1234, 28, "euler", "simple", 3.5, None)
    assert (info.prompt, info.negative_prompt, info.width, info.height) == ("a fox in snow", None, 896, 1152)
    assert info.family == "flux"
    assert info.model and info.model.name == "flux1-dev"
    assert info.vae and info.vae.name == "ae"


def test_sdxl_refiner():
    graph = base_graph()
    graph["20"] = node("CheckpointLoaderSimple", ckpt_name="sdxl/refiner.safetensors")
    graph["21"] = node(
        "KSampler", seed=42, steps=8, cfg=7.0, sampler_name="euler", scheduler="normal", denoise=0.25, model=["20", 0], positive=["6", 0], negative=["7", 0], latent_image=["3", 0]
    )
    graph["8"]["inputs"]["samples"] = ["21", 0]
    info = parse_graph(graph)
    assert info.model and info.model.name == "base"
    refiner = info.passes[0]
    assert (refiner.kind, refiner.steps, refiner.denoise) == ("refiner", 8, 0.25)
    assert refiner.model and refiner.model.name == "refiner"


def test_link_valued_widgets_and_string_nodes():
    graph = base_graph(seed=["30", 0], steps=["31", 0])
    graph["30"] = node("easy seed", seed=987654321)
    graph["31"] = node("MathExpression|pysssss", expression="a", a=["32", 0])
    graph["32"] = node("PrimitiveInt", value=33)
    graph["33"] = node("PrimitiveStringMultiline", value="a dog, from link")
    graph["6"]["inputs"]["text"] = ["33", 0]
    graph["5"]["inputs"]["width"] = ["32", 0]
    info = parse_graph(graph)
    assert (info.seed, info.steps, info.prompt, info.width) == (987654321, 33, "a dog, from link", 33)


def test_unknown_nodes_on_the_model_chain_and_loras():
    graph = base_graph(model=["41", 0])
    graph["40"] = node("LoraLoader", lora_name="style\\ink.safetensors", strength_model=0.7, strength_clip=0.5, model=["4", 0], clip=["4", 1])
    graph["41"] = node("SomeCustomPatch", strength=0.3, model=["42", 0])
    graph["42"] = node("ModelSamplingDiscrete", sampling="v_prediction", zsnr=True, model=["40", 0])
    graph["43"] = node("CLIPSetLastLayer", stop_at_clip_layer=-2, clip=["40", 1])
    graph["6"]["inputs"]["clip"] = ["43", 0]
    info = parse_graph(graph)
    assert info.model and info.model.name == "base"
    assert [(lora.name, lora.weight, lora.weight_clip) for lora in info.loras] == [("ink", 0.7, 0.5)]
    assert info.clip_skip == 2
    assert info.extras["SomeCustomPatch#41.strength"] == 0.3
    assert info.extras["ModelSamplingDiscrete#42.sampling"] == "v_prediction"


def test_missing_link_targets_do_not_break_the_walk():
    graph = base_graph(positive=["99", 0])  # a muted node: omitted before posting
    info = parse_graph(graph)
    assert info.prompt is None
    assert info.negative_prompt == "blurry"
    assert info.seed == 42


def test_subgraph_ids():
    graph = {
        "4": node("CheckpointLoaderSimple", ckpt_name="m.safetensors"),
        "12:5": node("EmptyLatentImage", width=512, height=768, batch_size=1),
        "12:6": node("CLIPTextEncode", text="inside a subgraph", clip=["4", 1]),
        "12:3": node(
            "KSampler",
            seed=1,
            steps=10,
            cfg=5,
            sampler_name="euler",
            scheduler="normal",
            denoise=1,
            model=["4", 0],
            positive=["12:6", 0],
            negative=["12:6", 0],
            latent_image=["12:5", 0],
        ),
        "8": node("VAEDecode", samples=["12:3", 0], vae=["4", 2]),
        "9": node("SaveImage", filename_prefix="x", images=["8", 0]),
    }
    info = parse_graph(graph)
    assert (info.prompt, info.width, info.height) == ("inside a subgraph", 512, 768)


def test_controlnet_polarity_and_record():
    graph = base_graph(positive=["50", 0], negative=["50", 1])
    graph["51"] = node("ControlNetLoader", control_net_name="cn/canny.safetensors")
    graph["52"] = node("LoadImage", image="pose.png")
    graph["50"] = node("ControlNetApplyAdvanced", strength=0.8, start_percent=0.0, end_percent=1.0, positive=["6", 0], negative=["7", 0], control_net=["51", 0], image=["52", 0])
    info = parse_graph(graph)
    assert (info.prompt, info.negative_prompt) == ("a cat", "blurry")
    assert info.controls == [{"type": "controlnet", "node": "50", "model": "canny", "strength": 0.8, "start_percent": 0.0, "end_percent": 1.0, "image": "pose.png"}]


def test_img2img_and_inpaint():
    graph = base_graph(denoise=0.55, latent_image=["60", 0])
    graph["61"] = node("LoadImage", image="init.png")
    graph["60"] = node("VAEEncode", pixels=["61", 0], vae=["4", 2])
    info = parse_graph(graph)
    assert (info.mode, info.denoise, info.extras["init_image"]) == ("img2img", 0.55, "init.png")
    graph["62"] = node("SetLatentNoiseMask", samples=["60", 0], mask=["61", 1])
    graph["3"]["inputs"]["latent_image"] = ["62", 0]
    assert parse_graph(graph).mode == "inpaint"


def test_sdxl_encoder_and_zero_out():
    graph = base_graph(negative=["70", 0])
    graph["6"] = node("CLIPTextEncodeSDXL", width=1024, height=1024, crop_w=0, crop_h=0, target_width=1024, target_height=1024, text_g="global", text_l="local", clip=["4", 1])
    graph["70"] = node("ConditioningZeroOut", conditioning=["6", 0])
    info = parse_graph(graph)
    assert info.prompt == "global\nlocal"
    assert info.negative_prompt is None


def test_save_node_matching_the_file_name_is_chosen():
    graph = base_graph()
    graph["20"] = node(
        "KSampler", seed=5, steps=5, cfg=1, sampler_name="lcm", scheduler="simple", denoise=1, model=["4", 0], positive=["6", 0], negative=["7", 0], latent_image=["5", 0]
    )
    graph["21"] = node("VAEDecode", samples=["20", 0], vae=["4", 2])
    graph["22"] = node("SaveImage", filename_prefix="drafts/fast", images=["21", 0])
    assert parse_graph(graph, "fast_00003_.png").seed == 5
    assert parse_graph(graph, "ComfyUI_00003_.png").seed == 42


def test_save_node_prefix_with_server_side_tokens():
    graph = base_graph()
    graph["20"] = node(
        "KSampler", seed=5, steps=5, cfg=1, sampler_name="lcm", scheduler="simple", denoise=1, model=["4", 0], positive=["6", 0], negative=["7", 0], latent_image=["5", 0]
    )
    graph["21"] = node("VAEDecode", samples=["20", 0], vae=["4", 2])
    # Stored before the server fills in the date and size; the file carries the values.
    graph["22"] = node("SaveImage", filename_prefix="%year%-%month%-%day%/fast_%width%x%height%", images=["21", 0])
    assert parse_graph(graph, "fast_1024x1024_00003_.png").seed == 5
    assert parse_graph(graph, "ComfyUI_00003_.png").seed == 42
    # A prefix that only starts the name loses to one that gives it exactly.
    graph["9"]["inputs"]["filename_prefix"] = "fast"
    graph["22"]["inputs"]["filename_prefix"] = "fast_%batch_num%"
    assert parse_graph(graph, "fast_2_00001_.png").seed == 5


def test_64_bit_seeds_stay_exact():
    seed = 2**64 - 1
    info = parse_graph(base_graph(seed=seed))
    assert info.seed == seed
    # On the wire a seed beyond JavaScript's safe range is a string (Pydantic v2; v1 keeps a number).
    assert json.loads(info.model_dump_json())["seed"] in (str(seed), seed)
    if PYDANTIC_V2:
        assert json.loads(info.model_dump_json())["seed"] == str(seed)


def test_workflow_only():
    workflow = {
        "nodes": [
            {"id": 4, "type": "CheckpointLoaderSimple", "mode": 0, "inputs": [], "widgets_values": ["model.safetensors"]},
            {"id": 5, "type": "EmptyLatentImage", "mode": 0, "inputs": [], "widgets_values": [512, 640, 1]},
            {"id": 6, "type": "CLIPTextEncode", "mode": 0, "inputs": [{"name": "clip", "link": 3}], "widgets_values": ["a castle"]},
            {"id": 7, "type": "CLIPTextEncode", "mode": 0, "inputs": [{"name": "clip", "link": 4}], "widgets_values": ["fog"]},
            {
                "id": 3,
                "type": "KSampler",
                "mode": 0,
                "inputs": [{"name": "model", "link": 1}, {"name": "positive", "link": 5}, {"name": "negative", "link": 6}, {"name": "latent_image", "link": 2}],
                "widgets_values": [156680208700286, "randomize", 20, 8, "euler", "normal", 1],
            },
            {"id": 8, "type": "VAEDecode", "mode": 0, "inputs": [{"name": "samples", "link": 7}, {"name": "vae", "link": 8}]},
            {"id": 9, "type": "SaveImage", "mode": 0, "inputs": [{"name": "images", "link": 9}], "widgets_values": ["ComfyUI"]},
            {"id": 10, "type": "Note", "mode": 0, "inputs": [], "widgets_values": ["ignored"]},
        ],
        "links": [
            [1, 4, 0, 3, 0, "MODEL"],
            [2, 5, 0, 3, 3, "LATENT"],
            [3, 4, 1, 6, 0, "CLIP"],
            [4, 4, 1, 7, 0, "CLIP"],
            [5, 6, 0, 3, 1, "C"],
            [6, 7, 0, 3, 2, "C"],
            [7, 3, 0, 8, 0, "L"],
            [8, 4, 2, 8, 1, "V"],
            [9, 8, 0, 9, 0, "I"],
        ],
        "extra": {"frontendVersion": "1.20.0"},
        "version": 0.4,
    }
    assert workflow_to_prompt(workflow)["3"]["inputs"]["seed"] == 156680208700286
    raw = RawMetadata(chunks={"workflow": json.dumps(workflow)})
    info = ComfyUIParser().parse(raw, "ComfyUI_00001_.png")
    assert (info.seed, info.steps, info.cfg_scale, info.prompt, info.negative_prompt, info.width, info.height) == (156680208700286, 20, 8, "a castle", "fog", 512, 640)
    assert info.warnings[0].startswith("workflow only")
    assert info.platform_version == "1.20.0"
    assert info.sources == ["workflow"]


def test_webui_parameters_on_a_comfyui_file_are_secondary():
    raw = RawMetadata(
        chunks={"prompt": json.dumps(base_graph()), "parameters": "x\nSteps: 5, Sampler: Euler, Seed: 9, Hires upscale: 2, Hires steps: 3, ADetailer model: face_yolov8n.pt"}
    )
    info = ComfyUIParser().parse(raw)
    assert info.platform == "comfyui"
    assert info.seed == 42
    assert info.passes[0].kind == "hires"
    assert "parameters" in info.sources
    assert info.extras["parameters.ADetailer model"] == "face_yolov8n.pt"
    assert "parameters.Hires steps" not in info.extras


def test_detect_needs_json_shaped_chunks():
    parser = ComfyUIParser()
    assert parser.detect(RawMetadata(chunks={"prompt": '{"a": 1}'}))
    assert not parser.detect(RawMetadata(chunks={"prompt": "a plain text prompt"}))
    with pytest.raises(ValueError):
        parser.parse(RawMetadata(chunks={"prompt": '{"a": 1}'}))
