"""ComfyUI: walk the embedded API graph (``prompt``) to the values that made the image.

The recipe (AGENTS.md §5): find the save node that wrote this file, walk the image/latent chain
upstream to the samplers on it (the first is the base pass, later ones are hires, refiner or
detailer passes), then follow the base sampler's inputs to its prompts, model, LoRAs, size and
VAE. Custom node packs are treated as opaque, with heuristics for
the common shapes; nothing keys on ``_meta.title``, which is localised.
"""

import json
import re
from dataclasses import dataclass, field
from typing import Any

from hanaikada.core.metadata.models import GenerationInfo, LoraRef, ModelRef, Pass, RawMetadata
from hanaikada.core.metadata.parsers.comfy_graph import Graph, is_link, unwrap, workflow_nodes
from hanaikada.core.metadata.parsers.common import dedupe, extra_value, file_stem, to_float, to_int, to_str
from hanaikada.core.metadata.samplers import normalize_sampler

SAMPLER_CLASSES = {"KSampler", "KSamplerAdvanced", "SamplerCustom", "SamplerCustomAdvanced"}
SAMPLER_FIELDS = ("seed", "noise_seed", "steps", "cfg", "sampler_name", "scheduler", "latent_image")
OUTPUT_CLASSES = {"SaveImage", "PreviewImage", "SaveImageAdvanced", "SaveAnimatedWEBP", "SaveAnimatedPNG", "SaveImageWebsocket"}
SPINE_INPUTS = ("samples", "latent_image", "latent", "image", "images", "pixels", "image_1", "image1", "input_image", "LATENT", "IMAGE", "latents")
TEXT_INPUTS = ("text", "text_g", "t5xxl", "clip_l", "clip_g", "prompt", "positive", "populated_text", "string", "wildcard_text", "text_positive", "user_prompt")
CONDITIONING_HINTS = ("conditioning", "cond", "positive", "negative")
CLIP_TYPE_FAMILY = {
    "sdxl": "sdxl",
    "sd3": "sd3",
    "flux": "flux",
    "flux2": "flux2",
    "stable_cascade": "stable-cascade",
    "hunyuan_video": "hunyuan-video",
    "hunyuan_image": "hunyuan-image",
    "hidream": "hidream",
    "wan": "wan",
    "lumina2": "lumina2",
    "chroma": "chroma",
    "qwen_image": "qwen-image",
    "cosmos": "cosmos",
    "mochi": "mochi",
    "ltxv": "ltxv",
    "pixart": "pixart",
    "omnigen2": "omnigen2",
    "ace": "ace",
}
MAX_EXTRAS = 300
MAX_DEPTH = 40

# Positional widget tables for a workflow-only file (§4): the non-link inputs in declaration
# order, with "control" standing for the control_after_generate companion value.
WIDGETS: dict[str, list[str]] = {
    "KSampler": ["seed", "control", "steps", "cfg", "sampler_name", "scheduler", "denoise"],
    "KSamplerAdvanced": ["add_noise", "noise_seed", "control", "steps", "cfg", "sampler_name", "scheduler", "start_at_step", "end_at_step", "return_with_leftover_noise"],
    "SamplerCustom": ["add_noise", "noise_seed", "control", "cfg"],
    "EmptyLatentImage": ["width", "height", "batch_size"],
    "EmptySD3LatentImage": ["width", "height", "batch_size"],
    "CLIPTextEncode": ["text"],
    "CLIPTextEncodeFlux": ["clip_l", "t5xxl", "guidance"],
    "CheckpointLoaderSimple": ["ckpt_name"],
    "UNETLoader": ["unet_name", "weight_dtype"],
    "VAELoader": ["vae_name"],
    "CLIPLoader": ["clip_name", "type", "device"],
    "DualCLIPLoader": ["clip_name1", "clip_name2", "type", "device"],
    "LoraLoader": ["lora_name", "strength_model", "strength_clip"],
    "LoraLoaderModelOnly": ["lora_name", "strength_model"],
    "CLIPSetLastLayer": ["stop_at_clip_layer"],
    "SaveImage": ["filename_prefix"],
    "RandomNoise": ["noise_seed", "control"],
    "KSamplerSelect": ["sampler_name"],
    "BasicScheduler": ["scheduler", "steps", "denoise"],
    "CFGGuider": ["cfg"],
    "FluxGuidance": ["guidance"],
    "LatentUpscale": ["upscale_method", "width", "height", "crop"],
    "LatentUpscaleBy": ["upscale_method", "scale_by"],
    "ImageScaleBy": ["upscale_method", "scale_by"],
    "UpscaleModelLoader": ["model_name"],
    "ControlNetLoader": ["control_net_name"],
}


def parse_json(text: str | None) -> Any:
    """ComfyUI's front-end accepts NaN and Infinity; so does Python's json."""
    if text is None or not text.strip():
        return None
    return json.loads(text)


def looks_like_prompt(obj: Any) -> bool:
    return isinstance(obj, dict) and any(isinstance(n, dict) and isinstance(n.get("class_type"), str) for n in obj.values())


def looks_like_workflow(obj: Any) -> bool:
    return isinstance(obj, dict) and isinstance(obj.get("nodes"), list)


@dataclass
class SamplerRead:
    node: str
    seed: int | None = None
    steps: int | None = None
    cfg: float | None = None
    sampler: str | None = None
    scheduler: str | None = None
    denoise: float | None = None
    model: tuple[str, int] | None = None
    positive: tuple[str, int] | None = None
    negative: tuple[str, int] | None = None
    latent: tuple[str, int] | None = None


@dataclass
class Walk:
    """State shared by one parse: which inputs were mapped, and what the chains yielded."""

    graph: Graph
    mapped: set[tuple[str, str]] = field(default_factory=set)
    loras: list[LoraRef] = field(default_factory=list)
    controls: list[dict[str, Any]] = field(default_factory=list)
    guidance: float | None = None
    clip_skip: int | None = None
    family: str | None = None
    warnings: list[str] = field(default_factory=list)

    def value(self, node: str | None, name: str) -> Any:
        if node is None:
            return None
        self.mapped.add((node, name))
        return self.graph.value(node, name)

    # -- samplers --------------------------------------------------------------------------------

    def is_sampler(self, node: str) -> bool:
        cls = self.graph.cls(node)
        if cls in SAMPLER_CLASSES:
            return True
        inputs = self.graph.inputs(node)
        if {"guider", "sampler", "sigmas"} <= set(inputs):
            return True
        return "positive" in inputs and "negative" in inputs and sum(f in inputs for f in SAMPLER_FIELDS) >= 2 and not self._is_text_encoder(node)

    def read_scheduler(self, node: str | None, read: SamplerRead) -> None:
        g = self.graph
        for _ in range(8):
            if node is None:
                return
            cls = g.cls(node)
            inputs = g.inputs(node)
            upstream = g.link(node, "sigmas")
            if cls in ("SplitSigmas", "SplitSigmasDenoise", "FlipSigmas", "SetFirstSigma") and upstream is not None:
                node = upstream[0]
                continue
            known = {
                "KarrasScheduler": "karras",
                "ExponentialScheduler": "exponential",
                "PolyexponentialScheduler": "polyexponential",
                "AlignYourStepsScheduler": "align_your_steps",
                "BetaSamplingScheduler": "beta",
                "SDTurboScheduler": "turbo",
                "LaplaceScheduler": "laplace",
                "VPScheduler": "vp",
                "GITSScheduler": "gits",
                "OptimalStepsScheduler": "optimal_steps",
            }
            if "scheduler" in inputs:
                read.scheduler = to_str(self.value(node, "scheduler"))
            elif cls in known:
                read.scheduler = known[cls]
            else:
                read.scheduler = cls
            if "steps" in inputs:
                read.steps = to_int(self.value(node, "steps"))
            if "denoise" in inputs:
                read.denoise = to_float(self.value(node, "denoise"))
            return

    def read_sampler(self, node: str) -> SamplerRead:
        g = self.graph
        cls = g.cls(node)
        inputs = g.inputs(node)
        read = SamplerRead(node=node)
        if "guider" in inputs or cls == "SamplerCustomAdvanced":
            noise = g.link(node, "noise")
            if noise is not None:
                read.seed = to_int(self.value(noise[0], "noise_seed") if "noise_seed" in g.inputs(noise[0]) else self.value(noise[0], "seed"))
            guider = g.link(node, "guider")
            if guider is not None:
                gid = guider[0]
                read.cfg = to_float(self.value(gid, "cfg")) if "cfg" in g.inputs(gid) else None
                read.model = g.link(gid, "model")
                read.positive = g.link(gid, "positive") or g.link(gid, "conditioning") or g.link(gid, "cond1")
                read.negative = g.link(gid, "negative")
            self._read_sampler_select(g.link(node, "sampler"), read)
            sigmas = g.link(node, "sigmas")
            self.read_scheduler(sigmas[0] if sigmas else None, read)
            read.latent = g.link(node, "latent_image")
            return read
        if cls == "SamplerCustom" or ("sigmas" in inputs and "sampler" in inputs):
            read.seed = to_int(self.value(node, "noise_seed") if "noise_seed" in inputs else self.value(node, "seed"))
            read.cfg = to_float(self.value(node, "cfg"))
            read.model, read.positive, read.negative = g.link(node, "model"), g.link(node, "positive"), g.link(node, "negative")
            self._read_sampler_select(g.link(node, "sampler"), read)
            sigmas = g.link(node, "sigmas")
            self.read_scheduler(sigmas[0] if sigmas else None, read)
            read.latent = g.link(node, "latent_image")
            return read
        seed_name = "seed" if "seed" in inputs else "noise_seed"
        read.seed = to_int(self.value(node, seed_name))
        read.steps = to_int(self.value(node, "steps"))
        read.cfg = to_float(self.value(node, "cfg"))
        read.sampler = to_str(self.value(node, "sampler_name"))
        read.scheduler = to_str(self.value(node, "scheduler"))
        if "denoise" in inputs:
            read.denoise = to_float(self.value(node, "denoise"))
        read.model = g.link(node, "model")
        read.positive = g.link(node, "positive")
        read.negative = g.link(node, "negative")
        read.latent = g.link(node, "latent_image") or g.link(node, "latent") or g.link(node, "samples")
        return read

    def _read_sampler_select(self, link: tuple[str, int] | None, read: SamplerRead) -> None:
        if link is None:
            return
        node = link[0]
        if "sampler_name" in self.graph.inputs(node):
            read.sampler = to_str(self.value(node, "sampler_name"))
        else:
            # SamplerEulerAncestral, SamplerDPMPP_2M_SDE, …: the class names the sampler.
            read.sampler = self.graph.cls(node)

    # -- prompts ---------------------------------------------------------------------------------

    def _text_inputs(self, node: str) -> list[str]:
        inputs = self.graph.inputs(node)
        return [name for name in TEXT_INPUTS if name in inputs and (isinstance(inputs[name], str) or is_link(inputs[name]))]

    def _is_text_encoder(self, node: str) -> bool:
        cls = self.graph.cls(node)
        inputs = self.graph.inputs(node)
        if cls.startswith("CLIPTextEncode"):
            return True
        if is_link(inputs.get("positive")) or is_link(inputs.get("negative")):
            return False  # positive/negative are conditioning here, not text
        has_clip = any("clip" in name.lower() and is_link(value) for name, value in inputs.items())
        texty = any(word in cls.lower() for word in ("encode", "prompt", "text"))
        return bool(self._text_inputs(node)) and (has_clip or texty)

    def text_of(self, node: str, name: str) -> str | None:
        value = self.value(node, name)
        return value if isinstance(value, str) else None

    def encoder_texts(self, node: str) -> list[str]:
        cls = self.graph.cls(node)
        if cls == "CLIPTextEncodeSDXL":
            texts = [self.text_of(node, "text_g"), self.text_of(node, "text_l")]
        elif cls == "CLIPTextEncodeFlux":
            texts = [self.text_of(node, "t5xxl"), self.text_of(node, "clip_l")]
            guidance = to_float(self.value(node, "guidance"))
            if guidance is not None and self.guidance is None:
                self.guidance = guidance
        elif cls == "CLIPTextEncodeSD3":
            texts = [self.text_of(node, "clip_g"), self.text_of(node, "clip_l"), self.text_of(node, "t5xxl")]
        else:
            names = self._text_inputs(node)
            texts = [self.text_of(node, names[0])] if names else []
        self.read_clip_chain(node)
        return dedupe([t for t in texts if t is not None and t.strip()])

    def trace_conditioning(self, link: tuple[str, int] | None, depth: int = 0) -> list[str]:
        """Every prompt text feeding one conditioning input, following combine, area and control nodes."""
        if link is None or depth > MAX_DEPTH:
            return []
        g = self.graph
        node, index = link
        cls = g.cls(node)
        inputs = g.inputs(node)
        if cls == "ConditioningZeroOut":
            return []
        if self._is_text_encoder(node):
            return self.encoder_texts(node)
        if cls == "FluxGuidance":
            self.guidance = to_float(self.value(node, "guidance")) if self.guidance is None else self.guidance
            return self.trace_conditioning(g.link(node, "conditioning"), depth + 1)
        if "control_net" in inputs:
            self._record_control(node)
        pos, neg = g.link(node, "positive"), g.link(node, "negative")
        if pos is not None and neg is not None:
            # ControlNetApplyAdvanced, InpaintModelConditioning, …: output 0 is positive, 1 negative.
            return self.trace_conditioning(pos if index == 0 else neg, depth + 1)
        texts: list[str] = []
        followed = False
        for name, target, out_index in g.link_inputs(node):
            if any(hint in name.lower() for hint in CONDITIONING_HINTS):
                texts.extend(self.trace_conditioning((target, out_index), depth + 1))
                followed = True
        if not followed and self._text_inputs(node):
            texts.extend(self.encoder_texts(node))
        return dedupe(texts)

    def _record_control(self, node: str) -> None:
        g = self.graph
        control: dict[str, Any] = {"type": "controlnet", "node": node}
        loader = g.link(node, "control_net")
        if loader is not None:
            name = to_str(self.value(loader[0], "control_net_name"))
            if name:
                control["model"] = file_stem(name)
        for key in ("strength", "start_percent", "end_percent"):
            if key in g.inputs(node):
                control[key] = extra_value(unwrap(self.value(node, key)))
        image = g.link(node, "image")
        if image is not None and "image" in g.inputs(image[0]):
            control["image"] = extra_value(self.value(image[0], "image"))
        if not any(c.get("node") == node for c in self.controls):
            self.controls.append(control)

    # -- model, CLIP and VAE chains ---------------------------------------------------------------

    def _add_lora(self, name: Any, weight: Any, weight_clip: Any = None) -> None:
        if not isinstance(name, str) or not name.strip():
            return
        stem = file_stem(name)
        for lora in self.loras:
            if lora.name == stem:
                return
        self.loras.append(LoraRef(name=stem, weight=to_float(weight), weight_clip=to_float(weight_clip)))

    def _read_lora_node(self, node: str) -> None:
        inputs = self.graph.inputs(node)
        if "lora_name" in inputs:
            self._add_lora(
                self.value(node, "lora_name"),
                self.value(node, "strength_model") if "strength_model" in inputs else self.value(node, "strength"),
                self.value(node, "strength_clip") if "strength_clip" in inputs else None,
            )
        for name, value in inputs.items():
            # rgthree's Power Lora Loader: lora_1 = {"on": true, "lora": "…", "strength": 0.9, "strengthTwo": …}
            if isinstance(value, dict) and "lora" in value and name.lower().startswith("lora"):
                self.mapped.add((node, name))
                if value.get("on", True):
                    self._add_lora(value.get("lora"), value.get("strength"), value.get("strengthTwo"))

    def read_model_chain(self, link: tuple[str, int] | None) -> ModelRef | None:
        g = self.graph
        node = link[0] if link else None
        for _ in range(MAX_DEPTH):
            if node is None:
                return None
            cls = g.cls(node)
            inputs = g.inputs(node)
            self._read_lora_node(node)
            if "IPAdapter" in cls or "ipadapter" in inputs:
                control = {"type": "ip_adapter", "node": node, "class": cls}
                if "weight" in inputs:
                    control["weight"] = extra_value(self.value(node, "weight"))
                if not any(c.get("node") == node for c in self.controls):
                    self.controls.append(control)
            for key in ("ckpt_name", "unet_name", "model_name", "model_path"):
                value = inputs.get(key)
                # "model_name" also names upscalers and detectors; it is a loader only without a model input.
                if not (isinstance(value, str) or is_link(value)) or (key in ("model_name", "model_path") and "model" in inputs):
                    continue
                name = to_str(self.value(node, key))
                if name:
                    return ModelRef(name=file_stem(name), path=name)
            nxt = g.link(node, "model")
            if nxt is None:
                links = [t for n, t, _ in g.link_inputs(node) if "model" in n.lower()]
                nxt = (links[0], 0) if links else None
            node = nxt[0] if nxt else None
        return None

    def read_clip_chain(self, encoder: str) -> None:
        g = self.graph
        links = [(t, i) for n, t, i in g.link_inputs(encoder) if "clip" in n.lower()]
        node = links[0][0] if links else None
        for _ in range(MAX_DEPTH):
            if node is None:
                return
            cls = g.cls(node)
            inputs = g.inputs(node)
            if cls == "CLIPSetLastLayer":
                layer = to_int(self.value(node, "stop_at_clip_layer"))
                if layer is not None and self.clip_skip is None:
                    self.clip_skip = abs(layer)
            self._read_lora_node(node)
            if "type" in inputs and ("clip_name" in inputs or "clip_name1" in inputs):
                clip_type = to_str(self.value(node, "type"))
                if clip_type and self.family is None:
                    self.family = CLIP_TYPE_FAMILY.get(clip_type.lower())
                return
            if cls == "TripleCLIPLoader" and self.family is None:
                self.family = "sd3"
            nxt = g.link(node, "clip")
            node = nxt[0] if nxt else None

    def read_vae(self, spine: list[str], base_index: int) -> ModelRef | None:
        g = self.graph
        for node in reversed(spine[:base_index]):
            vae = g.link(node, "vae")
            if vae is None:
                continue
            for _ in range(8):
                vid = vae[0]
                if "vae_name" in g.inputs(vid):
                    name = to_str(self.value(vid, "vae_name"))
                    return ModelRef(name=file_stem(name), path=name) if name else None
                nxt = g.link(vid, "vae")
                if nxt is None:
                    return None  # the checkpoint's own VAE
                vae = nxt
            return None
        return None

    # -- size and mode ---------------------------------------------------------------------------

    def read_latent(self, link: tuple[str, int] | None, info: GenerationInfo) -> None:
        g = self.graph
        node = link[0] if link else None
        mode: str | None = None
        for _ in range(MAX_DEPTH):
            if node is None:
                break
            cls = g.cls(node)
            inputs = g.inputs(node)
            if cls in ("SetLatentNoiseMask", "VAEEncodeForInpaint", "InpaintModelConditioning") or "mask" in inputs and cls.startswith(("VAEEncode", "Inpaint")):
                mode = mode or "inpaint"
            elif cls.startswith("VAEEncode"):
                mode = mode or "img2img"
            if "width" in inputs and "height" in inputs and ("batch_size" in inputs or cls.startswith("Empty")):
                info.width = to_int(self.value(node, "width"))
                info.height = to_int(self.value(node, "height"))
                mode = mode or "txt2img"
                break
            if cls == "LoadImage" or ("image" in inputs and isinstance(inputs["image"], str)):
                info.extras["init_image"] = extra_value(self.value(node, "image"))
                break
            nxt = None
            for name in ("samples", "latent", "latent_image", "pixels", "image", "LATENT"):
                nxt = g.link(node, name)
                if nxt is not None:
                    break
            node = nxt[0] if nxt else None
        info.mode = mode  # type: ignore[assignment]


# -- output node and the image/latent spine ------------------------------------------------------


def is_output(graph: Graph, node: str) -> bool:
    cls = graph.cls(node)
    inputs = graph.inputs(node)
    return cls in OUTPUT_CLASSES or (("save" in cls.lower() or "preview" in cls.lower()) and ("images" in inputs or "image" in inputs))


# The graph stores ``filename_prefix`` before the server fills these in (``compute_vars``, and
# ``%batch_num%`` in the save nodes), so they are matched as patterns. ComfyUI pads the date parts.
PREFIX_TOKENS = {
    "%width%": r"\d+",
    "%height%": r"\d+",
    "%year%": r"\d{4}",
    "%month%": r"\d{2}",
    "%day%": r"\d{2}",
    "%hour%": r"\d{2}",
    "%minute%": r"\d{2}",
    "%second%": r"\d{2}",
    "%batch_num%": r"\d+",
}
RE_PREFIX_TOKEN = re.compile(r"%[^%/\\]+%")


def prefix_pattern(prefix: str) -> str | None:
    """A regular expression for the file-name part of a save node's ``filename_prefix``."""
    base = prefix.replace("\\", "/").rstrip("/").rsplit("/", 1)[-1]
    if not base:
        return None
    parts: list[str] = []
    pos = 0
    for match in RE_PREFIX_TOKEN.finditer(base):
        parts.append(re.escape(base[pos : match.start()]))
        # Any other ``%…%`` (a custom node's own token) matches loosely.
        parts.append(PREFIX_TOKENS.get(match.group(0).lower(), ".*?"))
        pos = match.end()
    parts.append(re.escape(base[pos:]))
    return "".join(parts)


def pick_output(walk: Walk, file_name: str | None) -> str | None:
    g = walk.graph
    outputs = [n for n in g.nodes if is_output(g, n)]
    if not outputs:
        return None
    stem = file_name.rsplit(".", 1)[0] if file_name else ""
    if stem:
        # SaveImage names ``<prefix>_NNNNN_`` (others drop the last ``_``); a node whose prefix
        # gives exactly that wins over one whose prefix only starts the name.
        exact: list[str] = []
        starts: list[str] = []
        for node in outputs:
            prefix = g.value(node, "filename_prefix")
            pattern = prefix_pattern(prefix) if isinstance(prefix, str) else None
            if pattern is None:
                continue
            if re.fullmatch(f"{pattern}_\\d{{5}}_?", stem):
                exact.append(node)
            elif re.match(pattern, stem):
                starts.append(node)
        matching = exact or starts
        if matching:
            outputs = matching
        elif stem.startswith("ComfyUI_temp_"):
            previews = [n for n in outputs if "preview" in g.cls(n).lower()]
            outputs = previews or outputs

    def score(node: str) -> tuple[int, int]:
        not_preview = 0 if "preview" in g.cls(node).lower() else 1
        samplers = sum(1 for n in g.upstream(node) if walk.is_sampler(n))
        return (not_preview, samplers)

    return max(outputs, key=score)


def walk_spine(walk: Walk, start: str) -> list[str]:
    """From the output node upstream along the image/latent chain; the output node comes first."""
    g = walk.graph
    out: list[str] = []
    seen: set[str] = set()
    current: str | None = start
    while current is not None and current not in seen and len(out) < 500:
        seen.add(current)
        out.append(current)
        inputs = g.inputs(current)
        nxt: str | None = None
        for name in SPINE_INPUTS:
            hit = g.follow(inputs.get(name))
            if hit is not None:
                nxt = hit[0]
                break
        if nxt is None:
            for name, target, _ in g.link_inputs(current):
                if any(word in name.lower() for word in ("image", "latent", "sample", "pixel")):
                    nxt = target
                    break
        if nxt is None:
            links = list(g.link_inputs(current))
            if len(links) == 1:
                nxt = links[0][1]
        current = nxt
    return out


def upscale_pass(walk: Walk, node: str) -> Pass | None:
    """An upscale step on the spine: latent or pixel scaling, or an upscale model."""
    g = walk.graph
    cls = g.cls(node)
    inputs = g.inputs(node)
    if not ("upscale" in cls.lower() or cls in ("ImageScale", "ImageScaleBy", "ImageScaleToTotalPixels")):
        return None
    upscaler: str | None = None
    model = g.link(node, "upscale_model")
    if model is not None:
        upscaler = to_str(walk.value(model[0], "model_name"))
    elif isinstance(inputs.get("upscale_model"), str):
        upscaler = to_str(walk.value(node, "upscale_model"))
    elif "upscale_method" in inputs:
        upscaler = to_str(walk.value(node, "upscale_method"))
    factor = None
    for key in ("scale_by", "rescale_factor", "upscale_by", "scale"):
        if key in inputs:
            factor = to_float(walk.value(node, key))
            break
    width = to_int(walk.value(node, "width")) if "width" in inputs else None
    height = to_int(walk.value(node, "height")) if "height" in inputs else None
    return Pass(kind="upscale", upscaler=file_stem(upscaler) if upscaler else None, upscale=factor, width=width or None, height=height or None)


# -- the parser ----------------------------------------------------------------------------------


def workflow_to_prompt(workflow: dict[str, Any]) -> dict[str, Any]:
    """Rebuild an API graph from an editor workflow, for the core nodes whose widgets are known."""
    link_sources: dict[int, tuple[str, int]] = {}
    for link in workflow.get("links") or []:
        if isinstance(link, list) and len(link) >= 5:
            link_sources[int(link[0])] = (str(link[1]), int(link[2]))
        elif isinstance(link, dict) and "id" in link:
            link_sources[int(link["id"])] = (str(link.get("origin_id")), int(link.get("origin_slot") or 0))
    prompt: dict[str, Any] = {}
    for node in workflow_nodes(workflow):
        if node.get("mode") in (2, 4) or not isinstance(node.get("type"), str):
            continue
        cls = node["type"]
        inputs: dict[str, Any] = {}
        widgets = node.get("widgets_values")
        if isinstance(widgets, dict):
            inputs.update({k: v for k, v in widgets.items() if not isinstance(v, (dict, list))})
        elif isinstance(widgets, list) and cls in WIDGETS:
            for name, value in zip(WIDGETS[cls], widgets):
                if name != "control":
                    inputs[name] = value
        for slot in node.get("inputs") or []:
            if isinstance(slot, dict) and slot.get("link") is not None and slot.get("name"):
                source = link_sources.get(int(slot["link"]))
                if source is not None:
                    inputs[slot["name"]] = [source[0], source[1]]
        prompt[str(node.get("id"))] = {"class_type": cls, "inputs": inputs}
    return prompt


def parse_graph(prompt: dict[str, Any], file_name: str | None = None) -> GenerationInfo:
    """Walk an API graph into a GenerationInfo."""
    graph = Graph(prompt)
    walk = Walk(graph)
    info = GenerationInfo(platform="comfyui")
    output = pick_output(walk, file_name)
    spine = walk_spine(walk, output) if output else []
    on_spine = [n for n in spine if walk.is_sampler(n)]
    samplers = list(reversed(on_spine))
    if not samplers:
        candidates = [n for n in (graph.upstream(output) if output else graph.nodes) if walk.is_sampler(n)]
        if not candidates:
            candidates = [n for n in graph.nodes if walk.is_sampler(n)]
        # Upstream first: a sampler that depends on fewer other samplers ran earlier.
        samplers = sorted(candidates, key=lambda n: sum(1 for u in graph.upstream(n) if walk.is_sampler(u)))
    if output is not None:
        prefix = graph.value(output, "filename_prefix")
        walk.mapped.add((output, "filename_prefix"))
        if isinstance(prefix, str):
            info.extras["filename_prefix"] = prefix

    if not samplers:
        walk.warnings.append("no sampler node found")
        texts = [t for node in graph.nodes if graph.cls(node).startswith("CLIPTextEncode") for t in walk.encoder_texts(node)]
        info.prompts = dedupe(texts)
        info.prompt = "\n".join(info.prompts) or None
    else:
        base = walk.read_sampler(samplers[0])
        info.seed, info.steps, info.cfg_scale = base.seed, base.steps, base.cfg
        info.sampler, info.scheduler = base.sampler, base.scheduler
        info.sampler_norm = normalize_sampler(base.sampler)
        info.denoise = base.denoise if base.denoise is not None and base.denoise < 1 else None
        positives = walk.trace_conditioning(base.positive)
        negatives = walk.trace_conditioning(base.negative)
        info.prompts = positives
        info.prompt = "\n".join(positives) or None
        info.negative_prompt = "\n".join(negatives) or None
        info.model = walk.read_model_chain(base.model)
        walk.read_latent(base.latent, info)
        if info.mode is None and base.denoise is not None and base.denoise < 1:
            info.mode = "img2img"
        info.distilled_cfg = walk.guidance
        base_index = spine.index(samplers[0]) if samplers[0] in spine else len(spine)
        info.vae = walk.read_vae(spine, base_index)

        # Later samplers are passes; upscale steps between two samplers make the later one a hires pass.
        positions = {n: i for i, n in enumerate(spine)}
        previous_index = base_index
        for sampler_node in samplers[1:]:
            index = positions.get(sampler_node)
            between = spine[index + 1 : previous_index] if index is not None else []
            ups = [p for p in (upscale_pass(walk, n) for n in reversed(between)) if p is not None]
            read = walk.read_sampler(sampler_node)
            model = walk.read_model_chain(read.model)
            kind = "hires" if ups else ("refiner" if model and info.model and model.name != info.model.name else "sampler")
            step = Pass(
                kind=kind,  # type: ignore[arg-type]
                steps=read.steps,
                denoise=read.denoise,
                cfg_scale=read.cfg,
                sampler=read.sampler,
                scheduler=read.scheduler,
                model=model if model and (not info.model or model.name != info.model.name) else None,
            )
            if ups:
                step.upscaler = next((u.upscaler for u in ups if u.upscaler), None)
                factor = 1.0
                for u in ups:
                    factor *= u.upscale or 1.0
                step.upscale = factor if factor != 1.0 else None
                step.width = next((u.width for u in reversed(ups) if u.width), None)
                step.height = next((u.height for u in reversed(ups) if u.height), None)
            info.passes.append(step)
            if index is not None:
                previous_index = index
        last_index = min((positions[n] for n in samplers if n in positions), default=None)
        if last_index is not None:
            info.passes.extend(p for p in (upscale_pass(walk, n) for n in reversed(spine[1:last_index])) if p is not None)

    info.loras = walk.loras
    info.controls = walk.controls
    info.clip_skip = walk.clip_skip
    info.family = walk.family
    info.warnings.extend(walk.warnings)

    count = 0
    for node_id, node in graph.nodes.items():
        cls = node["class_type"]
        for name, value in graph.inputs(node_id).items():
            if is_link(value) or (node_id, name) in walk.mapped:
                continue
            value = unwrap(value)
            if isinstance(value, (dict, list)):
                continue
            if count >= MAX_EXTRAS:
                info.warnings.append(f"more than {MAX_EXTRAS} node inputs; the rest are only in the raw graph")
                return info
            info.extras[f"{cls}#{node_id}.{name}"] = extra_value(value, 500)
            count += 1
    return info


class ComfyUIParser:
    name = "comfyui"

    def detect(self, raw: RawMetadata) -> bool:
        from hanaikada.core.metadata.parsers.sd_webui import made_by_webui

        # The WebUI copies an init image's chunks into its output, so a ComfyUI graph next to a
        # generation infotext is the source image's, and the file is the WebUI's.
        if made_by_webui(raw):
            return False
        for key in ("prompt", "workflow"):
            text = raw.chunks.get(key)
            if text is not None and text.lstrip().startswith("{"):
                return True
        return False

    def parse(self, raw: RawMetadata, file_name: str | None = None) -> GenerationInfo:
        prompt = parse_json(raw.chunks.get("prompt")) if raw.chunks.get("prompt", "").lstrip().startswith("{") else None
        workflow_text = raw.chunks.get("workflow")
        workflow = parse_json(workflow_text) if workflow_text and workflow_text.lstrip().startswith("{") else None
        if isinstance(prompt, dict) and looks_like_prompt(prompt):
            info = parse_graph(prompt, file_name)
            info.sources.append("prompt")
        elif isinstance(workflow, dict) and looks_like_workflow(workflow):
            info = parse_graph(workflow_to_prompt(workflow), file_name)
            info.warnings.insert(0, "workflow only: values read from editor widgets")
        else:
            raise ValueError("neither prompt nor workflow is a ComfyUI graph")
        if isinstance(workflow, dict) and looks_like_workflow(workflow):
            info.sources.append("workflow")
            extra = workflow.get("extra")
            if isinstance(extra, dict) and isinstance(extra.get("frontendVersion"), str):
                info.platform_version = extra["frontendVersion"]

        # A ComfyUI image passed through the WebUI's Extras tab also carries its text chunks.
        from hanaikada.core.metadata.infotext import parse_infotext
        from hanaikada.core.metadata.parsers.sd_webui import apply_infotext, apply_postprocessing

        parameters = raw.chunks.get("parameters")
        if parameters and parameters.strip():
            secondary = GenerationInfo(platform="sd-webui")
            apply_infotext(secondary, parse_infotext(parameters))
            info.passes.extend(secondary.passes)
            for key, value in secondary.extras.items():
                info.extras[f"parameters.{key}"] = value
            info.sources.append("parameters")
        post = raw.chunks.get("postprocessing")
        if post is not None:
            if post.strip():
                apply_postprocessing(info, post)
            info.sources.append("postprocessing")
        return info
