"""The parser registry: detect a platform, then parse, in a fixed order.

Order matters: a WebUI Extras output of a ComfyUI image carries ``prompt``, ``workflow`` and
``postprocessing``, and must be read as ComfyUI; but a WebUI img2img output of one carries them
next to its own generation infotext, and is the WebUI's (``ComfyUIParser.detect`` steps aside).
An InvokeAI image is never anything else.
"""

import logging
from typing import Protocol, cast

from hanaikada.core.metadata.models import GenerationInfo, ParsedImage, Platform, RawMetadata
from hanaikada.core.metadata.parsers.comfyui import ComfyUIParser
from hanaikada.core.metadata.parsers.invokeai import InvokeAIParser
from hanaikada.core.metadata.parsers.novelai import NovelAIParser
from hanaikada.core.metadata.parsers.sd_webui import SdWebUIParser

logger = logging.getLogger(__name__)


class Parser(Protocol):
    name: str

    def detect(self, raw: RawMetadata) -> bool: ...

    def parse(self, raw: RawMetadata, file_name: str | None = None) -> GenerationInfo: ...


class ParserRegistry:
    def __init__(self, parsers: list[Parser] | None = None) -> None:
        self.parsers: list[Parser] = parsers if parsers is not None else [InvokeAIParser(), ComfyUIParser(), NovelAIParser(), SdWebUIParser()]

    def detect(self, raw: RawMetadata) -> Parser | None:
        return next((p for p in self.parsers if p.detect(raw)), None)

    def parse(self, raw: RawMetadata, file_name: str | None = None) -> ParsedImage:
        """Parse with the first parser that recognises the file.

        A parser that raises is caught: the result keeps the detected platform and the error, and
        the raw chunks are kept by the caller, so fixing a parser later only needs a re-parse.
        """
        parser = self.detect(raw)
        if parser is None:
            return ParsedImage(info=GenerationInfo(platform="none"), raw=raw)
        try:
            info = parser.parse(raw, file_name)
        except Exception as e:
            logger.debug("The %s parser failed on %s: %s", parser.name, file_name, e, exc_info=True)
            info = GenerationInfo(platform=cast(Platform, parser.name))
            return ParsedImage(info=info, raw=raw, error=f"{type(e).__name__}: {e}")
        return ParsedImage(info=info, raw=raw)
