"""Tags derived from an image's metadata.

Prompt tokens follow sd-webui-infinite-image-browsing's tokenisation: ``BREAK`` and newlines separate like commas, attention brackets and weights are stripped,
``<lora:…>`` tags are pulled out, tokens are lower-cased and de-duplicated. The negative prompt
is not tokenised; it is stored and searched instead.

Prompt tags are created for every token, but listed only once ``index.prompt_tag_min_count``
images share them, so a folder of unique prompts does not fill the tag list, and changing the
threshold takes effect at once.
"""

import re
from dataclasses import dataclass

from hanaikada.core.metadata.infotext import RE_EXTRA_NETWORK
from hanaikada.core.metadata.models import GenerationInfo

_BREAK = re.compile(r"\bBREAK\b")
_STRIP = re.compile(r"[\\/\[\](){}]")
_SPACES = re.compile(r"\s+")
_CJK = re.compile(r"^[　-鿿가-힯＀-￯]")
MAX_TOKEN_CHARS = 80


@dataclass(frozen=True)
class DerivedTag:
    name: str
    type: str


def valid_prompt_tag(token: str) -> bool:
    """IIB's rule: CJK-initial names up to 12 characters; others not over 8 words and 40 characters."""
    if not token or len(token) > MAX_TOKEN_CHARS:
        return False
    if _CJK.match(token):
        return len(token) <= 12
    return not (len(token.split()) > 8 and len(token) > 40)


def prompt_tokens(prompt: str | None) -> list[str]:
    if not prompt:
        return []
    text = RE_EXTRA_NETWORK.sub(",", prompt)
    text = _BREAK.sub(",", text).replace("\n", ",").replace("，", ",").replace("、", ",")
    text = re.sub(r">\s", "> ,", text)
    text = text.replace("_", " ").replace("-", " ")
    text = _STRIP.sub("", text)
    out: list[str] = []
    seen: set[str] = set()
    for part in text.split(","):
        token = part.split(":", 1)[0] if ":" in part else part
        token = _SPACES.sub(" ", token).strip().lower()
        if token and token not in seen and valid_prompt_tag(token):
            seen.add(token)
            out.append(token)
    return out


def derive_tags(info: GenerationInfo, width: int | None, height: int | None) -> list[DerivedTag]:
    """Every automatic tag for one image. Custom and board tags are not derived here."""
    tags: list[DerivedTag] = []
    if info.platform != "none":
        tags.append(DerivedTag(info.platform, "platform"))
    if width and height:
        tags.append(DerivedTag(f"{width}x{height}", "size"))
    if info.model is not None and info.model.name:
        tags.append(DerivedTag(info.model.name, "model"))
    if info.sampler_norm:
        tags.append(DerivedTag(info.sampler_norm, "sampler"))
    seen: set[str] = set()
    for lora in info.loras:
        if lora.name and lora.name not in seen:
            seen.add(lora.name)
            tags.append(DerivedTag(lora.name, "lora"))
    for token in prompt_tokens(info.prompt):
        tags.append(DerivedTag(token, "prompt"))
    return tags
