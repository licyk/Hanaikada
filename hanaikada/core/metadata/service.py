"""Read an image file, or its bytes, into a normalised record."""

from pathlib import Path

from hanaikada.core.metadata import containers
from hanaikada.core.metadata.models import ParsedImage, RawMetadata
from hanaikada.core.metadata.registry import ParserRegistry
from hanaikada.core.settings import SettingsService


class MetadataService:
    def __init__(self, settings: SettingsService | None = None, registry: ParserRegistry | None = None) -> None:
        """``settings`` may be None for a caller with no data directory, such as ``hanaikada info`` on a file."""
        self.settings = settings
        self.registry = registry or ParserRegistry()

    @property
    def _sidecar_extensions(self) -> list[str]:
        return self.settings.settings.library.sidecar_extensions if self.settings else [".txt", ".json"]

    def read_raw(self, path: Path, siblings: set[str] | None = None) -> RawMetadata:
        return containers.read_path(path, siblings, self._sidecar_extensions)

    def read(self, path: Path, siblings: set[str] | None = None) -> ParsedImage:
        """Read and parse one file. Raises UnsupportedFileError when it is not an image."""
        return self.parse(self.read_raw(path, siblings), path.name)

    def read_bytes(self, data: bytes, name: str | None = None) -> ParsedImage:
        """Parse an uploaded file without storing it (the PNG Info tab)."""
        return self.parse(containers.read_bytes(data), name)

    def parse(self, raw: RawMetadata, name: str | None = None) -> ParsedImage:
        return self.registry.parse(raw, name)
