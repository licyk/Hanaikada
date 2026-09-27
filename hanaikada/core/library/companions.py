"""Files that follow an image when it is moved, renamed or deleted.

A companion shares the image's stem: a ``.txt`` or ``.json`` sidecar, and for an InvokeAI root the
WebP in the ``thumbnails`` folder. Another *image* with the same stem is never a companion — the
WebUI's "Export for 4chan" writes ``00012-seed.png`` and ``00012-seed.jpg`` as two images — and a
sidecar shared with such a twin stays where it is unless the twin goes too.
"""

from pathlib import Path


def sidecars_of(image: Path, sidecar_extensions: list[str], image_extensions: list[str], moving_together: set[Path] | None = None) -> list[Path]:
    """The sidecars that belong to ``image`` alone (or to images moving with it)."""
    stem = image.stem
    parent = image.parent
    twins = [parent / f"{stem}{ext}" for ext in image_extensions if f"{stem}{ext}" != image.name]
    shared = any(t.is_file() and (moving_together is None or t not in moving_together) for t in twins)
    if shared:
        return []
    out: list[Path] = []
    for ext in sidecar_extensions:
        candidate = parent / f"{stem}{ext}"
        if candidate != image and candidate.is_file():
            out.append(candidate)
    return out


def invokeai_thumbnail(image_rel: str, output_rel: str, thumbs_rel: str) -> str | None:
    """``outputs/images/[sub/]x.png`` → ``outputs/images/thumbnails/[sub/]x.webp``."""
    prefix = f"{output_rel}/" if output_rel else ""
    if not image_rel.startswith(prefix):
        return None
    inner = image_rel[len(prefix) :]
    stem = inner.rsplit(".", 1)[0]
    return f"{thumbs_rel}/{stem}.webp"
