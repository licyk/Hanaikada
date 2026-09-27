"""The A1111 infotext grammar: tokenising, quoting and the composite values inside it.

Reimplemented from the format, not from WebUI code (AGENTS.md §5). Unlike the WebUI, nothing
here fills defaults, drops keys or resolves module names: those are behaviours of the WebUI's
interface, not facts about the image.
"""

import json
import re
from dataclasses import dataclass, field

# The WebUI's own patterns (modules/infotext_utils.py): a key, then a quoted or unquoted value.
RE_PARAM = re.compile(r'\s*([\w\s\-\/]+):\s*("(?:\\.|[^\\"])+"|[^,]*)(?:,|$)')
RE_SIZE = re.compile(r"^\s*(\d+)\s*x\s*(\d+)\s*$")
RE_EXTRA_NETWORK = re.compile(r"<(\w+):([^>]+)>")
NEGATIVE_PREFIX = "Negative prompt:"
MIN_PARAM_PAIRS = 3


@dataclass
class Infotext:
    prompt: str = ""
    negative_prompt: str | None = None
    params: dict[str, str] = field(default_factory=dict)
    """Every key of the parameter line, in order, with values unquoted but otherwise as written."""
    trailing: dict[str, str] = field(default_factory=dict)
    """``Key: value`` lines after the parameter line, as some extensions write (Dynamic Prompts' templates)."""


def unquote(value: str) -> str:
    """Undo ``quote()``: a value that starts and ends with a double quote is a JSON string."""
    if len(value) >= 2 and value[0] == '"' and value[-1] == '"':
        try:
            decoded = json.loads(value)
        except ValueError:
            return value
        if isinstance(decoded, str):
            return decoded
    return value


def quote(value: object) -> str:
    """The WebUI's ``quote()``: JSON-encode a value containing a comma, a newline or a colon."""
    text = str(value)
    if "," not in text and "\n" not in text and ":" not in text:
        return text
    return json.dumps(text, ensure_ascii=False)


def parse_params(line: str) -> dict[str, str]:
    """Tokenise one ``Key: value, Key: value`` line."""
    out: dict[str, str] = {}
    for key, value in RE_PARAM.findall(line):
        key = key.strip()
        if not key:
            continue
        out[key] = unquote(value.strip())
    return out


def _is_param_line(line: str) -> bool:
    return len(RE_PARAM.findall(line)) >= MIN_PARAM_PAIRS


def looks_like_infotext(text: str | None) -> bool:
    """Whether ``text`` has the shape of an infotext: a parameter line, or a negative prompt."""
    if not text or not text.strip():
        return False
    lines = text.strip().split("\n")
    if any(line.strip().startswith(NEGATIVE_PREFIX) for line in lines):
        return True
    return any(_is_param_line(line) and "Steps:" in line for line in lines) or _is_param_line(lines[-1])


def parse_infotext(text: str) -> Infotext:
    """Split an infotext into its prompt, negative prompt and parameters.

    As the WebUI does, the last line is the parameter line only when it holds at least three
    pairs. In addition, when the last lines are ``Key: value`` lines written after a parameter
    line that starts with ``Steps:``, they are kept apart instead of joining the prompt.
    """
    lines = text.strip().replace("\r\n", "\n").split("\n")
    result = Infotext()
    param_index: int | None = None
    if lines and _is_param_line(lines[-1]):
        param_index = len(lines) - 1
    else:
        for i in range(len(lines) - 2, -1, -1):
            if lines[i].lstrip().startswith("Steps:") and _is_param_line(lines[i]):
                after = lines[i + 1 :]
                if all(re.match(r"^\s*[\w\s\-\/]+:\s", line) for line in after if line.strip()):
                    param_index = i
                break
    if param_index is not None:
        result.params = parse_params(lines[param_index])
        for line in lines[param_index + 1 :]:
            key, _, value = line.partition(":")
            if key.strip():
                result.trailing[key.strip()] = value.strip()
        lines = lines[:param_index]

    prompt: list[str] = []
    negative: list[str] | None = None
    for line in lines:
        line = line.strip()
        if negative is None and line.startswith(NEGATIVE_PREFIX):
            negative = [line[len(NEGATIVE_PREFIX) :].strip()]
            continue
        (negative if negative is not None else prompt).append(line)
    result.prompt = "\n".join(prompt).strip("\n")
    result.negative_prompt = "\n".join(negative).strip("\n") if negative is not None else None
    return result


def split_size(value: str | None) -> tuple[int, int] | None:
    """``"1024x768"`` → ``(1024, 768)``."""
    if not value:
        return None
    match = RE_SIZE.match(value)
    return (int(match.group(1)), int(match.group(2))) if match else None


def parse_name_list(value: str) -> dict[str, str]:
    """``"name: hash, name2: hash2"`` (``Lora hashes``, ``TI hashes``) → ``{name: hash}``.

    Split on commas, then on the first colon, as the WebUI's LoRA extension does.
    """
    out: dict[str, str] = {}
    for part in value.split(","):
        name, sep, rest = part.partition(":")
        if sep and name.strip():
            out[name.strip()] = rest.strip()
    return out


def parse_json_object(value: str | None) -> dict[str, object] | None:
    if not value:
        return None
    try:
        obj = json.loads(value)
    except ValueError:
        return None
    return obj if isinstance(obj, dict) else None


def parse_unit(value: str) -> dict[str, str]:
    """A ``ControlNet N`` value: ``"Module: canny, Model: x [hash], Weight: 1.0, …"``. Not JSON."""
    out: dict[str, str] = {}
    for part in value.split(", "):
        key, sep, rest = part.partition(": ")
        if sep:
            out[key.strip()] = rest.strip()
    return out


@dataclass
class ExtraNetwork:
    kind: str
    name: str
    te: float | None = None
    unet: float | None = None


def _float(text: str) -> float | None:
    try:
        return float(text)
    except ValueError:
        return None


def extra_networks(prompt: str) -> list[ExtraNetwork]:
    """``<lora:name:0.8>``, ``<lora:name:te=0.5:unet=1>``, ``<lyco:…>``, ``<hypernet:…>`` in a prompt."""
    out: list[ExtraNetwork] = []
    for kind, args in RE_EXTRA_NETWORK.findall(prompt):
        parts = args.split(":")
        net = ExtraNetwork(kind=kind.lower(), name=parts[0].strip())
        positional = [p for p in parts[1:] if "=" not in p]
        named = dict(p.split("=", 1) for p in parts[1:] if "=" in p)
        if positional:
            net.te = _float(positional[0])
        if len(positional) > 1:
            net.unet = _float(positional[1])
        if "te" in named:
            net.te = _float(named["te"])
        if "unet" in named:
            net.unet = _float(named["unet"])
        if net.name:
            out.append(net)
    return out


def name_and_hash(value: str) -> tuple[str, str | None]:
    """``"model_name [0123abcd]"`` → ``("model_name", "0123abcd")``."""
    match = re.match(r"^(.*?)\s*\[([0-9a-fA-Fx]+)\]\s*$", value)
    if match:
        return match.group(1).strip(), match.group(2)
    return value.strip(), None
