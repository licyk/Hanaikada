"""NovelAI: PNG chunks ``Software = NovelAI``, ``Description`` (the prompt) and ``Comment`` (JSON).

The WebUI converts these into an infotext when it reads them; here the JSON is mapped directly, with the V4 caption objects read as well.
"""

import json
import re
from typing import Any

from hanaikada.core.metadata.models import GenerationInfo, ModelRef, RawMetadata
from hanaikada.core.metadata.parsers.common import dedupe, extra_value, to_float, to_int, to_str
from hanaikada.core.metadata.samplers import normalize_sampler

MAPPED = {"prompt", "uc", "steps", "scale", "seed", "sampler", "width", "height", "noise_schedule", "cfg_rescale", "strength", "v4_prompt", "v4_negative_prompt", "version"}


def _comment(raw: RawMetadata) -> dict[str, Any] | None:
    text = raw.chunks.get("Comment")
    if not text or not text.lstrip().startswith("{"):
        return None
    try:
        data = json.loads(text)
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def _captions(value: Any) -> list[str]:
    caption = value.get("caption") if isinstance(value, dict) else None
    if not isinstance(caption, dict):
        return []
    out = [to_str(caption.get("base_caption")) or ""]
    for char in caption.get("char_captions") or []:
        if isinstance(char, dict):
            out.append(to_str(char.get("char_caption")) or "")
    return [c for c in out if c]


class NovelAIParser:
    name = "novelai"

    def detect(self, raw: RawMetadata) -> bool:
        return (raw.chunks.get("Software") or "").strip() == "NovelAI" and _comment(raw) is not None

    def parse(self, raw: RawMetadata, file_name: str | None = None) -> GenerationInfo:
        data = _comment(raw)
        if data is None:
            raise ValueError("Comment is not a JSON object")
        info = GenerationInfo(platform="novelai", sources=["Comment"])
        v4 = _captions(data.get("v4_prompt"))
        info.prompt = to_str(data.get("prompt")) or to_str(raw.chunks.get("Description")) or (v4[0] if v4 else None)
        info.prompts = dedupe([p for p in [info.prompt, *v4[1:]] if p])
        v4_negative = _captions(data.get("v4_negative_prompt"))
        info.negative_prompt = to_str(data.get("uc")) or (v4_negative[0] if v4_negative else None)
        info.steps = to_int(data.get("steps"))
        info.cfg_scale = to_float(data.get("scale"))
        info.cfg_rescale = to_float(data.get("cfg_rescale")) or None
        info.seed = to_int(data.get("seed"))
        info.sampler = to_str(data.get("sampler"))
        info.sampler_norm = normalize_sampler(info.sampler)
        info.scheduler = to_str(data.get("noise_schedule"))
        info.width, info.height = to_int(data.get("width")), to_int(data.get("height"))
        strength = to_float(data.get("strength"))
        if strength is not None and "image" in str(data.get("request_type", "")).lower() or (strength is not None and strength < 1 and "noise" in data):
            info.denoise = strength
            info.mode = "img2img"
        else:
            info.mode = "txt2img"
        source = to_str(raw.chunks.get("Source"))
        if source:
            # "NovelAI Diffusion V4.5 4BB8B1D7": a model name and a short hash.
            match = re.match(r"^(.*?)\s+([0-9A-Fa-f]{8})$", source.strip())
            info.model = ModelRef(name=match.group(1), hash=match.group(2), hash_kind="unknown") if match else ModelRef(name=source)
        if data.get("version") is not None:
            info.platform_version = str(data["version"])
        for key, value in data.items():
            if key not in MAPPED and value is not None:
                info.extras[key] = extra_value(value, 1000)
        return info
