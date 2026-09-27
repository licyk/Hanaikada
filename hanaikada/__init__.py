"""Hanaikada: browse, search and manage images made with Stable Diffusion WebUI, ComfyUI and InvokeAI.

To embed the web UI and API in another application:

    from hanaikada import HanaikadaServer, ImageRoot

    server = HanaikadaServer(image_roots=[ImageRoot("/srv/sd-webui", layout="sd-webui")], port=0)
    print(server.start())   # http://127.0.0.1:54123
"""

from typing import TYPE_CHECKING, Any

from hanaikada.version import VERSION

if TYPE_CHECKING:
    from hanaikada.embed import HanaikadaServer, ImageRoot, serve

__all__ = ["VERSION", "HanaikadaServer", "ImageRoot", "serve"]

_LAZY = {"HanaikadaServer", "ImageRoot", "serve"}


def __getattr__(name: str) -> Any:
    """Import the server lazily, so ``hanaikada version`` does not pay for FastAPI."""
    if name in _LAZY:
        from hanaikada import embed

        return getattr(embed, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list[str]:
    return sorted(__all__)
