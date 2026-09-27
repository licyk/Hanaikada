"""InvokeAI: ``invokeai_metadata``, with ``invokeai_graph`` as the fallback.

The rules are in AGENTS.md §5. ``invokeai_metadata`` is a flat JSON
object in which every key is optional and unknown keys pass through, so absent means "not set".
Both model-identifier shapes are accepted: the current ``{key, hash, name, base, type}`` and the
3.x ``{model_name, base_model, model_type}``.
"""

import json
import re
import shlex
from itertools import pairwise
from typing import Any

from hanaikada.core.metadata.models import GenerationInfo, LoraRef, ModelRef, Pass, RawMetadata
from hanaikada.core.metadata.parsers.common import extra_value, to_bool, to_float, to_int, to_str
from hanaikada.core.metadata.samplers import normalize_sampler, split_invokeai_scheduler

LEGACY_KEYS = ("invokeai", "sd-metadata", "dream", "Dream")
MODES = ("txt2img", "img2img", "inpaint", "outpaint")
# generation_mode prefixes → family, for when the model identifier carries no base.
MODE_FAMILIES = {
    "sdxl": "sdxl",
    "flux": "flux",
    "flux2": "flux2",
    "sd3": "sd-3",
    "cogview4": "cogview4",
    "z_image": "z-image",
    "qwen_image": "qwen-image",
    "anima": "anima",
    "krea2": "krea-2",
    "wan": "wan",
    "ernie_image": "ernie-image",
    "ideogram4": "ideogram-4",
}
# Mapped to typed fields, or summarised in ``controls``: not repeated in ``extras``.
MAPPED_KEYS = {
    "positive_prompt",
    "negative_prompt",
    "width",
    "height",
    "seed",
    "steps",
    "cfg_scale",
    "guidance",
    "cfg_rescale_multiplier",
    "scheduler",
    "clip_skip",
    "strength",
    "model",
    "model_name",
    "vae",
    "loras",
    "generation_mode",
    "app_version",
    "hrf_enabled",
    "hrf_method",
    "hrf_strength",
    "refiner_model",
    "refiner_cfg_scale",
    "refiner_steps",
    "refiner_scheduler",
    "controlnets",
    "ipAdapters",
    "t2iAdapters",
    "ref_images",
    "regions",
    "canvas_v2_metadata",
}


def model_ref(value: Any) -> ModelRef | None:
    """A ModelIdentifierField in either shape, or a bare name."""
    if isinstance(value, str) and value.strip():
        return ModelRef(name=value)
    if not isinstance(value, dict):
        return None
    name = to_str(value.get("name")) or to_str(value.get("model_name")) or to_str(value.get("key"))
    if not name:
        return None
    raw_hash = to_str(value.get("hash"))
    hash_value, kind = None, None
    if raw_hash:
        algorithm, sep, digest = raw_hash.partition(":")
        hash_value = digest if sep else raw_hash
        kind = "blake3" if sep and algorithm == "blake3" else "unknown"
    return ModelRef(name=name, hash=hash_value, hash_kind=kind)  # type: ignore[arg-type]


def model_base(value: Any) -> str | None:
    if isinstance(value, dict):
        return to_str(value.get("base")) or to_str(value.get("base_model"))
    return None


def _control(kind: str, item: Any) -> dict[str, Any] | None:
    if not isinstance(item, dict):
        return None
    out: dict[str, Any] = {"type": kind}
    config = item.get("config") if isinstance(item.get("config"), dict) else item
    if isinstance(item.get("config"), dict):
        out["type"] = to_str(config.get("type")) or kind
        if "isEnabled" in item:
            out["enabled"] = bool(item["isEnabled"])
    for key in ("model", "control_model", "ip_adapter_model", "t2i_adapter_model", "controlAdapter"):
        ref = model_ref(config.get(key))
        if ref is not None:
            out["model"] = ref.name
            break
    for key in ("weight", "control_weight", "control_mode", "method", "begin_step_percent", "end_step_percent", "beginEndStepPct"):
        if key in config:
            out[key] = extra_value(config[key], 200)
    return out


def apply_metadata(info: GenerationInfo, meta: dict[str, Any]) -> None:
    """Map an ``invokeai_metadata`` object (or a ``core_metadata`` node) onto ``info``."""
    info.prompt = to_str(meta.get("positive_prompt"))
    info.negative_prompt = to_str(meta.get("negative_prompt"))
    if info.prompt:
        info.prompts = [info.prompt]
    style = to_str(meta.get("positive_style_prompt"))
    if style and style != info.prompt:
        info.prompts.append(style)
    info.width, info.height = to_int(meta.get("width")), to_int(meta.get("height"))
    info.seed = to_int(meta.get("seed"))
    info.steps = to_int(meta.get("steps"))
    info.cfg_scale = to_float(meta.get("cfg_scale"))
    info.distilled_cfg = to_float(meta.get("guidance"))
    info.cfg_rescale = to_float(meta.get("cfg_rescale_multiplier")) or None
    scheduler = to_str(meta.get("scheduler"))
    if scheduler:
        info.sampler, info.scheduler = split_invokeai_scheduler(scheduler)
        info.sampler_norm = normalize_sampler(info.sampler)
    info.clip_skip = to_int(meta.get("clip_skip"))
    info.denoise = to_float(meta.get("strength"))
    info.model = model_ref(meta.get("model")) or model_ref(meta.get("model_name"))
    info.vae = model_ref(meta.get("vae"))
    info.platform_version = to_str(meta.get("app_version"))

    mode = to_str(meta.get("generation_mode")) or ""
    prefix = ""
    for candidate in MODES:
        if mode == candidate or mode.endswith("_" + candidate):
            info.mode = candidate  # type: ignore[assignment]
            prefix = mode[: -len(candidate)].rstrip("_")
            break
    info.family = model_base(meta.get("model")) or MODE_FAMILIES.get(prefix)

    for item in meta.get("loras") or []:
        if not isinstance(item, dict):
            continue
        ref = model_ref(item.get("model")) or model_ref(item.get("lora"))
        if ref is not None:
            info.loras.append(LoraRef(name=ref.name, weight=to_float(item.get("weight")), hash=ref.hash))

    if to_bool(meta.get("hrf_enabled")):
        info.passes.append(Pass(kind="hires", denoise=to_float(meta.get("hrf_strength")), upscaler=to_str(meta.get("hrf_method"))))
    refiner = model_ref(meta.get("refiner_model"))
    if refiner is not None:
        step = Pass(kind="refiner", model=refiner, steps=to_int(meta.get("refiner_steps")), cfg_scale=to_float(meta.get("refiner_cfg_scale")))
        refiner_scheduler = to_str(meta.get("refiner_scheduler"))
        if refiner_scheduler:
            step.sampler, step.scheduler = split_invokeai_scheduler(refiner_scheduler)
        info.passes.append(step)

    for key, kind in (("controlnets", "controlnet"), ("ipAdapters", "ip_adapter"), ("t2iAdapters", "t2i_adapter"), ("ref_images", "reference_image")):
        for item in meta.get(key) or []:
            control = _control(kind, item)
            if control is not None:
                info.controls.append(control)
    canvas = meta.get("canvas_v2_metadata")
    if isinstance(canvas, dict):
        for layer in canvas.get("controlLayers") or []:
            if isinstance(layer, dict) and isinstance(layer.get("controlAdapter"), dict):
                adapter = layer["controlAdapter"]
                control = {"type": to_str(adapter.get("type")) or "control_layer", "enabled": bool(layer.get("isEnabled", True))}
                ref = model_ref(adapter.get("model"))
                if ref is not None:
                    control["model"] = ref.name
                if "weight" in adapter:
                    control["weight"] = extra_value(adapter["weight"], 200)
                info.controls.append(control)
        for key in ("rasterLayers", "inpaintMasks", "regionalGuidance", "controlLayers"):
            layers = canvas.get(key)
            if isinstance(layers, list) and layers:
                info.extras[f"canvas.{key}"] = len(layers)
    regions = meta.get("regions")
    if isinstance(regions, list) and regions:
        info.extras["regions"] = len(regions)

    for key, value in meta.items():
        if key not in MAPPED_KEYS and value is not None:
            info.extras[key] = extra_value(value, 1000)


# -- the graph fallback --------------------------------------------------------------------------


class InvokeGraph:
    def __init__(self, graph: dict[str, Any]) -> None:
        nodes = graph.get("nodes")
        self.nodes: dict[str, dict[str, Any]] = {str(k): v for k, v in nodes.items() if isinstance(v, dict)} if isinstance(nodes, dict) else {}
        self.edges_in: dict[tuple[str, str], tuple[str, str]] = {}
        for edge in graph.get("edges") or []:
            try:
                source, dest = edge["source"], edge["destination"]
                self.edges_in[(str(dest["node_id"]), str(dest["field"]))] = (str(source["node_id"]), str(source["field"]))
            except (KeyError, TypeError):
                continue

    def field(self, node_id: str, name: str, depth: int = 0) -> Any:
        """A node's input: the value arriving by edge when there is one, else the static value.

        A primitive node (``integer``, ``string``) outputs its ``value``, so an edge from an output
        the source does not hold as an input is read from the source's ``value``.
        """
        edge = self.edges_in.get((node_id, name))
        if edge is None or depth >= 8:
            return self.nodes.get(node_id, {}).get(name)
        source_id, source_field = edge
        if source_field in self.nodes.get(source_id, {}) or (source_id, source_field) in self.edges_in:
            return self.field(source_id, source_field, depth + 1)
        return self.field(source_id, "value", depth + 1)

    def of_type(self, *types: str, suffix: str | None = None) -> list[str]:
        """Node ids whose type is one of ``types``, or ends with ``suffix``."""
        out = []
        for node_id, node in self.nodes.items():
            node_type = str(node.get("type", ""))
            if node_type in types or (suffix is not None and node_type.endswith(suffix)):
                out.append(node_id)
        return out


def apply_graph(info: GenerationInfo, graph: dict[str, Any]) -> None:
    g = InvokeGraph(graph)
    core = g.of_type("core_metadata")
    if core:
        node_id = core[0]
        fields = {k for k in g.nodes[node_id] if k not in ("id", "type", "is_intermediate", "use_cache")}
        fields |= {name for (dest, name) in g.edges_in if dest == node_id}
        apply_metadata(info, {name: g.field(node_id, name) for name in fields})
        return
    info.warnings.append("no core_metadata node; values read from the graph's nodes")
    for nid in g.of_type("noise"):
        info.seed = to_int(g.field(nid, "seed"))
        info.width, info.height = to_int(g.field(nid, "width")), to_int(g.field(nid, "height"))
    denoisers = g.of_type("denoise_latents", "flux_denoise", "sd3_denoise", suffix="_denoise")
    for nid in denoisers[:1]:
        info.steps = to_int(g.field(nid, "steps") or g.field(nid, "num_steps"))
        info.cfg_scale = to_float(g.field(nid, "cfg_scale"))
        info.distilled_cfg = to_float(g.field(nid, "guidance"))
        scheduler = to_str(g.field(nid, "scheduler"))
        if scheduler:
            info.sampler, info.scheduler = split_invokeai_scheduler(scheduler)
            info.sampler_norm = normalize_sampler(info.sampler)
        start = to_float(g.field(nid, "denoising_start"))
        if start:
            info.denoise = round(1 - start, 4)
            info.mode = "img2img"
        if info.seed is None:
            info.seed = to_int(g.field(nid, "seed"))
        for key, attr in (
            ("positive_conditioning", "prompt"),
            ("positive_text_conditioning", "prompt"),
            ("negative_conditioning", "negative_prompt"),
            ("negative_text_conditioning", "negative_prompt"),
        ):
            edge = g.edges_in.get((nid, key))
            if edge is None:
                continue
            encoder = edge[0]
            text = to_str(g.field(encoder, "prompt")) or to_str(g.field(encoder, "positive_prompt"))
            if text and getattr(info, attr) is None:
                setattr(info, attr, text)
    for nid in g.nodes:
        node_type = str(g.nodes[nid].get("type", ""))
        if node_type.endswith("model_loader") and info.model is None:
            info.model = model_ref(g.field(nid, "model"))
            base = model_base(g.field(nid, "model"))
            info.family = info.family or base
        if node_type in ("lora_loader", "lora_selector", "sdxl_lora_loader", "flux_lora_loader"):
            ref = model_ref(g.field(nid, "lora"))
            if ref is not None:
                info.loras.append(LoraRef(name=ref.name, weight=to_float(g.field(nid, "weight")), hash=ref.hash))
        if node_type == "clip_skip" and info.clip_skip is None:
            info.clip_skip = to_int(g.field(nid, "skipped_layers"))
    if info.prompt:
        info.prompts = [info.prompt]
    if info.mode is None and info.seed is not None:
        info.mode = "txt2img"


# -- legacy chunks (InvokeAI 1.x–3.0 beta) --------------------------------------------------------


def apply_legacy(info: GenerationInfo, key: str, text: str) -> None:
    info.platform_version = "legacy"
    if key in ("dream", "Dream"):
        try:
            tokens = shlex.split(text)
        except ValueError:
            tokens = text.split()
        if tokens:
            prompt = tokens[0]
            negatives = re.findall(r"\[([^\]]*)\]", prompt)
            info.prompt = re.sub(r"\s*\[[^\]]*\]", "", prompt).strip() or None
            info.negative_prompt = ", ".join(n.strip() for n in negatives) or None
        flags = {"-s": "steps", "-S": "seed", "-W": "width", "-H": "height", "-C": "cfg", "-A": "sampler", "-f": "strength"}
        for flag, value in pairwise(tokens[1:]):
            name = flags.get(flag)
            if name == "steps":
                info.steps = to_int(value)
            elif name == "seed":
                info.seed = to_int(value)
            elif name == "width":
                info.width = to_int(value)
            elif name == "height":
                info.height = to_int(value)
            elif name == "cfg":
                info.cfg_scale = to_float(value)
            elif name == "sampler":
                info.sampler = value
            elif name == "strength":
                info.denoise = to_float(value)
        info.sampler_norm = normalize_sampler(info.sampler)
        return
    data = json.loads(text)
    if not isinstance(data, dict):
        raise TypeError(f"{key} is not a JSON object")
    image = data.get("image") if isinstance(data.get("image"), dict) else data
    prompt = image.get("prompt") or image.get("positive_conditioning")
    if isinstance(prompt, list):
        prompt = ", ".join(str(p.get("prompt", "")) if isinstance(p, dict) else str(p) for p in prompt)
    info.prompt = to_str(prompt)
    info.negative_prompt = to_str(image.get("negative_conditioning"))
    info.seed = to_int(image.get("seed"))
    info.steps = to_int(image.get("steps"))
    info.cfg_scale = to_float(image.get("cfg_scale"))
    info.width, info.height = to_int(image.get("width")), to_int(image.get("height"))
    info.sampler = to_str(image.get("sampler")) or to_str(image.get("scheduler"))
    info.sampler_norm = normalize_sampler(info.sampler)
    info.denoise = to_float(image.get("strength"))
    kind = to_str(image.get("type"))
    if kind in MODES:
        info.mode = kind  # type: ignore[assignment]
    weights = to_str(data.get("model_weights"))
    if weights:
        info.model = ModelRef(name=weights, hash=to_str(data.get("model_hash")), hash_kind="unknown" if data.get("model_hash") else None)
    if data.get("app_version"):
        info.extras["app_version"] = str(data["app_version"])


class InvokeAIParser:
    name = "invokeai"

    def detect(self, raw: RawMetadata) -> bool:
        return any(key.startswith("invokeai_") for key in raw.chunks) or any(key in raw.chunks for key in LEGACY_KEYS)

    def parse(self, raw: RawMetadata, file_name: str | None = None) -> GenerationInfo:
        info = GenerationInfo(platform="invokeai")
        metadata = raw.chunks.get("invokeai_metadata")
        graph = raw.chunks.get("invokeai_graph")
        workflow = raw.chunks.get("invokeai_workflow")
        parsed_meta = json.loads(metadata) if metadata else None
        if isinstance(parsed_meta, dict):
            apply_metadata(info, parsed_meta)
            info.sources.append("invokeai_metadata")
        elif graph:
            parsed_graph = json.loads(graph)
            if not isinstance(parsed_graph, dict) or not isinstance(parsed_graph.get("nodes"), dict):
                raise TypeError("invokeai_graph has no nodes")
            apply_graph(info, parsed_graph)
            info.sources.append("invokeai_graph")
        else:
            legacy = next((k for k in LEGACY_KEYS if k in raw.chunks), None)
            if legacy is not None:
                apply_legacy(info, legacy, raw.chunks[legacy])
                info.sources.append(legacy)
            elif workflow:
                info.warnings.append("workflow only: no generation parameters")
        if graph and "invokeai_graph" not in info.sources:
            info.sources.append("invokeai_graph")
        if workflow:
            info.sources.append("invokeai_workflow")
            try:
                document = json.loads(workflow)
            except ValueError:
                document = None
            if isinstance(document, dict):
                if to_str(document.get("name")):
                    info.extras["workflow_name"] = document["name"]
                meta = document.get("meta")
                if isinstance(meta, dict) and to_str(meta.get("version")):
                    info.extras["workflow_version"] = meta["version"]
        return info
