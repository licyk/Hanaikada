"""The normalised generation record every parser produces, and the raw metadata it came from."""

from typing import Any, Literal

from pydantic import Field, StrictBool, StrictFloat, StrictInt, StrictStr

from hanaikada.core.record import BigInt, Record

Platform = Literal["sd-webui", "comfyui", "invokeai", "novelai", "none"]
PLATFORMS: list[str] = ["sd-webui", "comfyui", "invokeai", "novelai", "none"]
Mode = Literal["txt2img", "img2img", "inpaint", "outpaint", "upscale"]
HashKind = Literal["sha256-10", "sha256-12", "blake3", "autov2", "unknown"]
# Strict, so that a value keeps its type on both Pydantic versions: v1 coerces through a union
# left to right, which turned True into "True" when a response was validated again.
ExtraValue = StrictBool | StrictInt | StrictFloat | StrictStr | None


class ModelRef(Record):
    name: str
    """Display name: the file stem, or InvokeAI's model name."""
    path: str | None = None
    """As written by the platform, such as ComfyUI's path relative to its model folder."""
    hash: str | None = None
    """As written; never recomputed."""
    hash_kind: HashKind | None = None


class LoraRef(Record):
    name: str
    weight: float | None = None
    """The model (UNet) strength."""
    weight_clip: float | None = None
    """The text-encoder strength, when the platform records one apart from the model's."""
    hash: str | None = None


class Pass(Record):
    """A sampling or upscaling step after the base pass: hires fix, refiner, upscale."""

    kind: Literal["hires", "refiner", "upscale", "sampler"]
    steps: int | None = None
    denoise: float | None = None
    cfg_scale: float | None = None
    sampler: str | None = None
    scheduler: str | None = None
    upscaler: str | None = None
    upscale: float | None = None
    width: int | None = None
    height: int | None = None
    model: ModelRef | None = None


class GenerationInfo(Record):
    """What an image says about how it was made, in one shape for every platform."""

    platform: Platform = "none"
    platform_version: str | None = None
    mode: Mode | None = None
    family: str | None = None
    """sd-1, sdxl, flux, … when the platform says so (InvokeAI's base, ComfyUI's CLIP loader type)."""
    prompt: str | None = None
    negative_prompt: str | None = None
    prompts: list[str] = Field(default_factory=list)
    """Every positive text, when a graph has several."""
    seed: BigInt | None = None
    steps: int | None = None
    cfg_scale: float | None = None
    distilled_cfg: float | None = None
    cfg_rescale: float | None = None
    sampler: str | None = None
    """The platform's own spelling."""
    scheduler: str | None = None
    sampler_norm: str | None = None
    """A normalised alias for search, in ComfyUI's vocabulary: euler_ancestral, dpmpp_2m, …"""
    width: int | None = None
    """Requested generation size, before hires fix or upscaling."""
    height: int | None = None
    denoise: float | None = None
    clip_skip: int | None = None
    model: ModelRef | None = None
    vae: ModelRef | None = None
    loras: list[LoraRef] = Field(default_factory=list)
    passes: list[Pass] = Field(default_factory=list)
    controls: list[dict[str, Any]] = Field(default_factory=list)
    """ControlNet units, IP adapters and reference images, summarised."""
    extras: dict[str, ExtraValue] = Field(default_factory=dict)
    """Every parameter not mapped above, verbatim."""
    sources: list[str] = Field(default_factory=list)
    """Which chunks were used: parameters, prompt, invokeai_metadata, exif:UserComment, sidecar:txt, …"""
    warnings: list[str] = Field(default_factory=list)


class RawMetadata(Record):
    """Everything readable in the file, before any platform logic."""

    format: str | None = None
    width: int | None = None
    """Displayed size, after the EXIF orientation is applied."""
    height: int | None = None
    mode: str | None = None
    frames: int = 1
    chunks: dict[str, str] = Field(default_factory=dict)
    """Text entries keyed as the platform keys them: parameters, prompt, workflow, invokeai_metadata, UserComment, …"""
    chunk_sources: dict[str, str] = Field(default_factory=dict)
    """Where each chunk was found: png:tEXt, png:iTXt, png:zTXt, png:comf, exif:UserComment, exif:IFD0, gif:comment, sidecar:txt."""
    info: dict[str, str] = Field(default_factory=dict)
    """Other container and EXIF entries as strings (Software, dpi, Make, …), for display."""
    sidecars: list[str] = Field(default_factory=list)
    """Names of files beside the image that share its stem."""

    def text(self, *keys: str) -> str | None:
        """The first of ``keys`` present, as text."""
        for key in keys:
            value = self.chunks.get(key)
            if value is not None:
                return value
        return None


class ParsedImage(Record):
    info: GenerationInfo
    raw: RawMetadata
    error: str | None = None
    """Set when a parser failed; ``info`` then carries only the detected platform."""
