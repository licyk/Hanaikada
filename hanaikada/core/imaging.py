"""Pillow, with the format plugins Hanaikada needs registered. Code that opens images imports
``Image`` from here rather than from ``PIL``, so a plugin is always in place first.

``pillow-jxl-plugin`` adds JPEG XL, but only once ``pillow_jxl`` is imported. It is a dependency;
if its native library cannot load, everything else still works and ``.jxl`` files stay unread.
"""

import logging

from PIL import Image, ImageOps

logger = logging.getLogger(__name__)

try:
    import pillow_jxl  # noqa: F401
except (ImportError, OSError) as e:
    logger.warning("JPEG XL images cannot be read: %s", e)

__all__ = ["Image", "ImageOps"]
