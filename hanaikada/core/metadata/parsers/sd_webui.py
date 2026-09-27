"""Stable Diffusion WebUI (A1111, Forge, Forge Classic, reForge, SD.Next): the infotext.

Every value in an infotext is a string; known keys are converted and moved to typed fields,
everything else stays in ``extras`` verbatim.
"""

import math

from hanaikada.core.metadata.infotext import (
    Infotext,
    extra_networks,
    looks_like_infotext,
    name_and_hash,
    parse_infotext,
    parse_json_object,
    parse_name_list,
    parse_params,
    parse_unit,
    split_size,
)
from hanaikada.core.metadata.models import GenerationInfo, LoraRef, ModelRef, Pass, RawMetadata
from hanaikada.core.metadata.parsers.common import file_stem, hash_kind, to_float, to_int
from hanaikada.core.metadata.samplers import normalize_sampler, split_webui_sampler

# Where an infotext can be, in the order the WebUI reads them. Only ``parameters`` is trusted
# without looking at its shape: a camera's UserComment or a GIF's comment can be anything.
INFOTEXT_KEYS = ("parameters", "UserComment", "comment", "sidecar:txt")
INPAINT_KEYS = ("Mask blur", "Inpaint area", "Masked content", "Mask mode", "Masked area padding", "Inpainting fill")
POSTPROCESS_PREFIX = "Postprocess "
SAME = ("Use same sampler", "Use same scheduler", "Use same checkpoint", "Use same choices")


def source_name(raw: RawMetadata, key: str) -> str:
    """How a chunk is named in ``GenerationInfo.sources``."""
    if key == "parameters":
        return "parameters"
    if key == "UserComment":
        return "exif:UserComment"
    if key == "comment":
        return raw.chunk_sources.get(key, "comment")
    return key


def is_postprocessing_only(text: str) -> bool:
    """An Extras-tab JPEG or WebP carries only ``Postprocess …`` pairs in its UserComment."""
    stripped = text.strip()
    if not stripped or "\n" in stripped:
        return False
    params = parse_params(stripped)
    return bool(params) and all(k.startswith(POSTPROCESS_PREFIX) for k in params)


def made_by_webui(raw: RawMetadata) -> bool:
    """Whether ``parameters`` records a generation (it has ``Steps``), not only text carried along."""
    text = raw.chunks.get("parameters")
    return bool(text and text.strip()) and "Steps" in parse_infotext(text).params


def carries_comfy_graph(raw: RawMetadata) -> bool:
    return any((raw.chunks.get(key) or "").lstrip().startswith("{") for key in ("prompt", "workflow"))


def old_first_pass_size(width: int, height: int) -> tuple[int, int]:
    """The base size the pre-2023 hires fix chose for ``First pass size: 0x0``: about 512×512
    pixels in the final aspect, rounded up to multiples of 64 (the WebUI's
    ``old_hires_fix_first_pass_dimensions``)."""
    scale = math.sqrt(512 * 512 / (width * height))
    return math.ceil(scale * width / 64) * 64, math.ceil(scale * height / 64) * 64


def find_infotext(raw: RawMetadata) -> tuple[str, str] | None:
    """The chunk key and text of the image's infotext, if it has one."""
    for key in INFOTEXT_KEYS:
        text = raw.chunks.get(key)
        if text is None:
            continue
        if key == "parameters" or looks_like_infotext(text) or is_postprocessing_only(text):
            return key, text
    return None


def _merge_lora(loras: list[LoraRef], name: str, weight: float | None = None, weight_clip: float | None = None, hash: str | None = None) -> None:
    """Add a LoRA, or fill the fields an earlier mention of it left empty."""
    for lora in loras:
        if lora.name == name:
            lora.weight = lora.weight if lora.weight is not None else weight
            lora.weight_clip = lora.weight_clip if lora.weight_clip is not None else weight_clip
            lora.hash = lora.hash if lora.hash is not None else hash
            return
    loras.append(LoraRef(name=name, weight=weight, weight_clip=weight_clip, hash=hash))


def apply_postprocessing(info: GenerationInfo, text: str, extras_prefix: str = "postprocessing.") -> None:
    """The Extras tab's own text: an upscale pass, and every other key under ``extras``."""
    params = parse_params(text.strip())
    if not params:
        return
    upscaler = params.pop("Postprocess upscaler", None)
    by = to_float(params.pop("Postprocess upscale by", None))
    to = split_size(params.pop("Postprocess upscale to", None))
    if upscaler or by or to:
        info.passes.append(Pass(kind="upscale", upscaler=upscaler, upscale=by, width=to[0] if to else None, height=to[1] if to else None))
    for key, value in params.items():
        info.extras[f"{extras_prefix}{key}"] = value
    info.mode = "upscale"


def apply_infotext(info: GenerationInfo, parsed: Infotext) -> None:
    """Map a parsed infotext onto ``info``. Keys that are not mapped go to ``extras`` unchanged."""
    params = dict(parsed.params)

    def take(key: str) -> str | None:
        value = params.pop(key, None)
        return value if value not in (None, "") else None

    info.prompt = parsed.prompt or None
    info.negative_prompt = parsed.negative_prompt or None
    if info.prompt:
        info.prompts = [info.prompt]

    info.steps = to_int(take("Steps"))
    sampler = take("Sampler")
    scheduler = take("Schedule type")
    if sampler == "Undefined":
        # Written by some versions for the default; the WebUI reads it as Euler with Simple.
        sampler, scheduler = "Euler", scheduler or "Simple"
    if sampler:
        info.sampler, suffix = split_webui_sampler(sampler)
        info.scheduler = scheduler or suffix
    else:
        info.scheduler = scheduler
    info.sampler_norm = normalize_sampler(info.sampler)
    info.cfg_scale = to_float(take("CFG scale"))
    info.distilled_cfg = to_float(take("Distilled CFG Scale"))
    info.cfg_rescale = to_float(take("Rescale CFG")) or None
    info.seed = to_int(take("Seed"))
    size = split_size(take("Size"))
    if size is None and "width" in params and "height" in params:
        size = (to_int(take("width")) or 0, to_int(take("height")) or 0)
    if size:
        info.width, info.height = size
    info.clip_skip = to_int(take("Clip skip"))

    hashes = parse_json_object(take("Hashes")) or {}
    model = take("Model")
    model_hash = take("Model hash") or (str(hashes["model"]) if hashes.get("model") else None)
    if model or model_hash:
        info.model = ModelRef(name=model or model_hash or "", hash=model_hash, hash_kind=hash_kind(model_hash))
    vae = take("VAE")
    vae_hash = take("VAE hash") or (str(hashes["vae"]) if hashes.get("vae") else None)
    if vae:
        info.vae = ModelRef(name=file_stem(vae), path=vae, hash=vae_hash, hash_kind=hash_kind(vae_hash))
    else:
        # Forge names its VAE and text encoders "Module 1", "Module 2", …; they stay in extras.
        for key, value in params.items():
            if key.startswith("Module ") and value and ("vae" in value.lower() or file_stem(value).lower() == "ae"):
                info.vae = ModelRef(name=file_stem(value), path=value)
                break

    denoise = to_float(take("Denoising strength"))
    hires_keys = [k for k in params if k.startswith("Hires ")]
    # Before 2023 the hires fix wrote the final size as ``Size`` and the base pass as ``First pass
    # size`` (0x0: chosen automatically), with no ``Hires`` keys: without this it reads as img2img.
    first_pass = split_size(params.get("First pass size"))
    if first_pass is not None and info.width and info.height:
        params.pop("First pass size")
        final = (info.width, info.height)
        info.width, info.height = first_pass if first_pass != (0, 0) else old_first_pass_size(*final)
        info.passes.append(Pass(kind="hires", denoise=denoise, upscaler=take("Hires upscaler"), width=final[0], height=final[1]))
        info.mode = "txt2img"
    elif hires_keys:
        upscale = to_float(take("Hires upscale"))
        resize = split_size(take("Hires resize"))
        if resize == (0, 0):
            resize = None
        if resize is None and upscale and info.width and info.height:
            resize = (int(info.width * upscale), int(info.height * upscale))
        hires_sampler = take("Hires sampler")
        hires_schedule = take("Hires schedule type")
        checkpoint = take("Hires checkpoint")
        hires_model = None
        if checkpoint and checkpoint not in SAME:
            name, h = name_and_hash(checkpoint)
            hires_model = ModelRef(name=name, hash=h, hash_kind=hash_kind(h))
        info.passes.append(
            Pass(
                kind="hires",
                steps=to_int(take("Hires steps")),
                denoise=denoise,
                cfg_scale=to_float(take("Hires CFG Scale")),
                sampler=hires_sampler if hires_sampler not in SAME else None,
                scheduler=hires_schedule if hires_schedule not in SAME else None,
                upscaler=take("Hires upscaler"),
                upscale=upscale,
                width=resize[0] if resize else None,
                height=resize[1] if resize else None,
                model=hires_model,
            )
        )
        info.mode = "txt2img"
    elif denoise is not None:
        info.denoise = denoise
        info.mode = "inpaint" if any(k in params for k in INPAINT_KEYS) else "img2img"
    else:
        info.mode = "txt2img"

    refiner = take("Refiner")
    if refiner:
        name, h = name_and_hash(refiner)
        info.passes.append(Pass(kind="refiner", model=ModelRef(name=name, hash=h, hash_kind=hash_kind(h))))

    upscaler = take("Postprocess upscaler")
    by = to_float(take("Postprocess upscale by"))
    if upscaler or by:
        info.passes.append(Pass(kind="upscale", upscaler=upscaler, upscale=by))

    info.platform_version = take("Version")

    # LoRAs: the prompt's <lora:…> tags give weights, "Lora hashes" and "Hashes" give hashes.
    for net in extra_networks(parsed.prompt or ""):
        if net.kind in ("lora", "lyco"):
            weight = net.unet if net.unet is not None else net.te
            _merge_lora(info.loras, net.name, weight=weight, weight_clip=net.te if net.unet is not None else None)
    lora_hashes = take("Lora hashes")
    if lora_hashes:
        for name, h in parse_name_list(lora_hashes).items():
            _merge_lora(info.loras, name, hash=h or None)
    for key, value in hashes.items():
        if key.startswith("lora:") and value:
            _merge_lora(info.loras, key[5:], hash=str(value))

    for key in [k for k in params if k.startswith("ControlNet ")]:
        value = take(key)
        if not value:
            continue
        unit = parse_unit(value)
        control: dict[str, object] = {"type": "controlnet", "index": to_int(key.split(" ", 1)[1])}
        control.update({k.lower().replace(" ", "_"): v for k, v in unit.items()})
        info.controls.append(control)

    for key, value in params.items():
        info.extras[key] = value
    for key, value in parsed.trailing.items():
        info.extras.setdefault(key, value)


class SdWebUIParser:
    name = "sd-webui"

    def detect(self, raw: RawMetadata) -> bool:
        return find_infotext(raw) is not None

    def parse(self, raw: RawMetadata, file_name: str | None = None) -> GenerationInfo:
        info = GenerationInfo(platform="sd-webui")
        found = find_infotext(raw)
        if found is not None:
            key, text = found
            info.sources.append(source_name(raw, key))
            if key != "parameters" and is_postprocessing_only(text):
                apply_postprocessing(info, text, extras_prefix="")
            else:
                apply_infotext(info, parse_infotext(text))
        post = raw.chunks.get("postprocessing")
        if post is not None and post.strip():
            info.sources.append("postprocessing")
            apply_postprocessing(info, post)
        if carries_comfy_graph(raw):
            info.warnings.append("carries the ComfyUI graph of its source image (prompt/workflow chunks)")
        return info
