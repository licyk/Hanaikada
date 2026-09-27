"""The index: image rows, tags, search, and the background scanner."""

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from hanaikada.core.index.service import IndexService

__all__ = ["IndexService"]


def __getattr__(name: str) -> Any:
    """Import the service lazily: the library's models import ``index.models``, and the service imports the library."""
    if name == "IndexService":
        from hanaikada.core.index.service import IndexService

        return IndexService
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
