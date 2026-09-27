"""InvokeAI and NovelAI parsers, and the registry's detection order and error handling."""

import json

import pytest

from hanaikada.core.metadata import MetadataService
from hanaikada.core.metadata.containers import read_path
from hanaikada.core.metadata.models import RawMetadata
from hanaikada.core.metadata.parsers.invokeai import InvokeAIParser
from hanaikada.core.metadata.parsers.novelai import NovelAIParser
from hanaikada.core.metadata.registry import ParserRegistry
from tests.helpers import FIXTURES, INFOTEXT, png_bytes, text_chunk


def invoke(meta: dict | None = None, graph: dict | None = None) -> RawMetadata:
    chunks = {}
    if meta is not None:
        chunks["invokeai_metadata"] = json.dumps(meta)
    if graph is not None:
        chunks["invokeai_graph"] = json.dumps(graph)
    return RawMetadata(chunks=chunks)


# -- InvokeAI --------------------------------------------------------------------------------------


def test_invokeai_6_9_fixture():
    info = InvokeAIParser().parse(read_path(FIXTURES / "invokeai_6.9.png"))
    assert (info.platform, info.platform_version, info.mode, info.family) == ("invokeai", "6.9.0", "txt2img", "sdxl")
    assert (info.seed, info.steps, info.cfg_scale, info.width, info.height) == (2443106208, 20, 5.0, 1024, 1344)
    assert (info.sampler, info.scheduler, info.sampler_norm) == ("euler", None, "euler")
    assert info.model and (info.model.name, info.model.hash_kind) == ("noobaiXLNAIXL_vPred10Version", "blake3")
    assert info.model.hash == "c7f40a013cd3516943bec5bff517c0218d8434f99ed52e427ac2c961b852f318"
    assert [(lora.name, lora.weight) for lora in info.loras] == [("ill-xl-01-MaidCode1023_2-000038_without_norm_block", 1.0)]
    assert info.extras == {"rand_device": "cuda", "seamless_x": False, "seamless_y": False}
    assert info.sources == ["invokeai_metadata", "invokeai_graph"]


def test_invokeai_legacy_identifier_shape():
    info = InvokeAIParser().parse(read_path(FIXTURES / "invokeai_legacy.png"))
    assert info.model and info.model.name == "SkunkMix-P7-5m3-ws"
    assert info.family == "sd-1"
    assert (info.seed, info.steps, info.cfg_scale) == (1542798571, 50, 6.5)


def test_invokeai_workflow_only():
    info = InvokeAIParser().parse(read_path(FIXTURES / "invokeai_workflow_only.png"))
    assert info.prompt is None
    assert info.warnings == ["workflow only: no generation parameters"]
    assert info.sources == ["invokeai_workflow"]
    assert info.extras["workflow_version"] == "1.0.0"


def test_invokeai_loras_old_and_new_and_karras_scheduler():
    meta = {
        "generation_mode": "img2img",
        "scheduler": "dpmpp_2m_k",
        "strength": 0.6,
        "loras": [
            {"model": {"key": "k", "hash": "blake3:aa", "name": "new", "base": "sd-1", "type": "lora"}, "weight": 0.5},
            {"lora": {"model_name": "old", "base_model": "sd-1"}, "weight": 0.8},
        ],
    }
    info = InvokeAIParser().parse(invoke(meta))
    assert (info.sampler, info.scheduler, info.sampler_norm) == ("dpmpp_2m", "karras", "dpmpp_2m")
    assert (info.mode, info.denoise) == ("img2img", 0.6)
    assert [(lora.name, lora.weight, lora.hash) for lora in info.loras] == [("new", 0.5, "aa"), ("old", 0.8, None)]


def test_invokeai_flux_without_negative():
    meta = {
        "generation_mode": "flux_txt2img",
        "positive_prompt": "a lake",
        "guidance": 4,
        "steps": 30,
        "seed": 3,
        "model": {"name": "FLUX Dev", "base": "flux", "hash": "blake3:x"},
    }
    info = InvokeAIParser().parse(invoke(meta))
    assert (info.prompt, info.negative_prompt, info.cfg_scale, info.distilled_cfg, info.family, info.mode) == ("a lake", None, None, 4.0, "flux", "txt2img")


def test_invokeai_refiner_hires_and_controls():
    meta = {
        "generation_mode": "sdxl_txt2img",
        "refiner_model": {"name": "refiner", "base": "sdxl-refiner"},
        "refiner_steps": 10,
        "refiner_scheduler": "euler_a",
        "hrf_enabled": True,
        "hrf_strength": 0.45,
        "hrf_method": "ESRGAN",
        "ref_images": [{"id": "r", "isEnabled": True, "config": {"type": "ip_adapter", "model": {"name": "ip-adapter-plus"}, "weight": 0.7}}],
        "controlnets": [{"control_model": {"model_name": "canny"}, "control_weight": 1}],
        "canvas_v2_metadata": {"controlLayers": [], "rasterLayers": [{"id": 1}], "inpaintMasks": [], "regionalGuidance": []},
    }
    info = InvokeAIParser().parse(invoke(meta))
    assert [(p.kind, p.model.name if p.model else p.upscaler) for p in info.passes] == [("hires", "ESRGAN"), ("refiner", "refiner")]
    assert info.passes[1].sampler == "euler_a"
    assert info.controls == [{"type": "controlnet", "model": "canny", "control_weight": 1}, {"type": "ip_adapter", "enabled": True, "model": "ip-adapter-plus", "weight": 0.7}]
    assert info.extras["canvas.rasterLayers"] == 1
    assert "canvas_v2_metadata" not in info.extras


def test_invokeai_graph_fallback_through_core_metadata_edges():
    graph = {
        "id": "sdxl_graph:x",
        "nodes": {
            "seed:1": {"type": "integer", "id": "seed:1", "value": 99},
            "pos:1": {"type": "string", "id": "pos:1", "value": "from the graph"},
            "core_metadata:1": {"type": "core_metadata", "id": "core_metadata:1", "steps": 30, "cfg_scale": 4.5, "scheduler": "euler_a", "model": {"name": "m", "base": "sdxl"}},
        },
        "edges": [
            {"source": {"node_id": "seed:1", "field": "value"}, "destination": {"node_id": "core_metadata:1", "field": "seed"}},
            {"source": {"node_id": "pos:1", "field": "value"}, "destination": {"node_id": "core_metadata:1", "field": "positive_prompt"}},
        ],
    }
    info = InvokeAIParser().parse(invoke(graph=graph))
    assert (info.seed, info.prompt, info.steps, info.sampler_norm, info.family) == (99, "from the graph", 30, "euler_ancestral", "sdxl")
    assert info.sources == ["invokeai_graph"]


def test_invokeai_graph_fallback_without_core_metadata():
    graph = {
        "nodes": {
            "loader": {"type": "sdxl_model_loader", "model": {"name": "base", "base": "sdxl"}},
            "p": {"type": "sdxl_compel_prompt", "prompt": "positive text"},
            "n": {"type": "sdxl_compel_prompt", "prompt": "negative text"},
            "noise": {"type": "noise", "seed": 5, "width": 832, "height": 1216},
            "den": {"type": "denoise_latents", "steps": 22, "cfg_scale": 6, "scheduler": "dpmpp_2m"},
        },
        "edges": [
            {"source": {"node_id": "p", "field": "conditioning"}, "destination": {"node_id": "den", "field": "positive_conditioning"}},
            {"source": {"node_id": "n", "field": "conditioning"}, "destination": {"node_id": "den", "field": "negative_conditioning"}},
        ],
    }
    info = InvokeAIParser().parse(invoke(graph=graph))
    assert (info.prompt, info.negative_prompt, info.seed, info.width, info.steps, info.cfg_scale) == ("positive text", "negative text", 5, 832, 22, 6.0)
    assert info.model and info.model.name == "base"
    assert info.warnings


def test_invokeai_legacy_chunks():
    raw = RawMetadata(
        chunks={
            "sd-metadata": json.dumps(
                {
                    "model_weights": "stable-diffusion-1.5",
                    "model_hash": "cc6cb27103417325ff94f52b7a5d2dde45a7515b25c255d8e396c90014281516",
                    "app_version": "2.3.0",
                    "image": {
                        "prompt": [{"prompt": "an owl", "weight": 1}],
                        "seed": 7,
                        "steps": 30,
                        "cfg_scale": 7.5,
                        "sampler": "k_lms",
                        "width": 512,
                        "height": 512,
                        "type": "txt2img",
                    },
                }
            )
        }
    )
    info = InvokeAIParser().parse(raw)
    assert (info.platform_version, info.prompt, info.seed, info.sampler_norm, info.model.name if info.model else None) == ("legacy", "an owl", 7, "lms", "stable-diffusion-1.5")
    dream = InvokeAIParser().parse(RawMetadata(chunks={"Dream": '"a red fox [blurry, text]" -s 50 -S 3357757885 -W 512 -H 768 -C 7.5 -A k_euler_a'}))
    assert (dream.prompt, dream.negative_prompt, dream.steps, dream.seed, dream.width, dream.height, dream.cfg_scale) == (
        "a red fox",
        "blurry, text",
        50,
        3357757885,
        512,
        768,
        7.5,
    )


# -- NovelAI ---------------------------------------------------------------------------------------


NOVELAI_COMMENT = {
    "prompt": "1girl, rain",
    "steps": 28,
    "height": 1216,
    "width": 832,
    "scale": 5,
    "uncond_scale": 0,
    "cfg_rescale": 0,
    "seed": 3071474384,
    "n_samples": 1,
    "noise_schedule": "karras",
    "sampler": "k_euler_ancestral",
    "sm": False,
    "uc": "lowres, bad anatomy",
    "request_type": "PromptGenerateRequest",
    "v4_prompt": {"caption": {"base_caption": "1girl, rain", "char_captions": [{"char_caption": "girl, umbrella", "centers": [{"x": 0.5, "y": 0.5}]}]}},
    "version": 1,
}


def novelai_raw() -> RawMetadata:
    return RawMetadata(
        chunks={
            "Title": "NovelAI generated image",
            "Description": "1girl, rain",
            "Software": "NovelAI",
            "Source": "NovelAI Diffusion V4.5 4BB8B1D7",
            "Comment": json.dumps(NOVELAI_COMMENT),
        }
    )


def test_novelai():
    info = NovelAIParser().parse(novelai_raw())
    assert (info.platform, info.prompt, info.negative_prompt, info.steps, info.cfg_scale, info.seed) == ("novelai", "1girl, rain", "lowres, bad anatomy", 28, 5.0, 3071474384)
    assert (info.sampler, info.sampler_norm, info.scheduler, info.width, info.height, info.mode) == ("k_euler_ancestral", "euler_ancestral", "karras", 832, 1216, "txt2img")
    assert info.prompts == ["1girl, rain", "girl, umbrella"]
    assert info.model and (info.model.name, info.model.hash) == ("NovelAI Diffusion V4.5", "4BB8B1D7")
    assert info.extras["request_type"] == "PromptGenerateRequest"


# -- The registry ------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("chunks", "platform"),
    [
        ({"invokeai_metadata": "{}", "parameters": INFOTEXT}, "invokeai"),
        # An Extras output of a ComfyUI image: its graph and the tab's own text.
        ({"prompt": '{"1": {"class_type": "KSampler", "inputs": {}}}', "postprocessing": "Postprocess upscale by: 2"}, "comfyui"),
        # A WebUI img2img output of a ComfyUI image: the copied graph next to a real infotext.
        ({"prompt": '{"1": {"class_type": "KSampler", "inputs": {}}}', "parameters": INFOTEXT}, "sd-webui"),
        ({"Software": "NovelAI", "Comment": json.dumps(NOVELAI_COMMENT), "parameters": INFOTEXT}, "novelai"),
        ({"parameters": INFOTEXT}, "sd-webui"),
        ({"UserComment": "A photo from my camera"}, "none"),
        ({}, "none"),
    ],
)
def test_detection_order(chunks, platform):
    assert ParserRegistry().parse(RawMetadata(chunks=chunks)).info.platform == platform


def test_webui_output_of_a_comfyui_image_is_the_webuis():
    graph = json.dumps({"3": {"class_type": "KSampler", "inputs": {"seed": 1, "steps": 5}}})
    parsed = ParserRegistry().parse(RawMetadata(chunks={"prompt": graph, "workflow": "{}", "parameters": INFOTEXT}))
    assert parsed.info.platform == "sd-webui"
    assert parsed.info.seed != 1 and parsed.info.steps
    assert any("ComfyUI graph" in w for w in parsed.info.warnings)


def test_broken_json_keeps_the_platform_and_the_raw_text():
    raw = RawMetadata(chunks={"prompt": '{"3": {"class_type": "KSampler", broken'})
    parsed = ParserRegistry().parse(raw)
    assert parsed.info.platform == "comfyui"
    assert parsed.error and parsed.error.startswith("JSONDecodeError")
    assert parsed.raw.chunks["prompt"].startswith('{"3"')


def test_service_reads_bytes_and_paths(tmp_path):
    service = MetadataService()
    data = png_bytes([text_chunk("parameters", INFOTEXT)])
    parsed = service.read_bytes(data, "upload.png")
    assert parsed.info.seed == 1234567890
    assert parsed.raw.format == "PNG"
    path = tmp_path / "a.png"
    path.write_bytes(data)
    assert service.read(path).info.model_dump() == parsed.info.model_dump()
