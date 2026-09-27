"""File responses that a browser can cache for a year.

URLs for files and thumbnails carry the file's mtime as ``?t=``, so a changed file gets a new URL
and an unchanged one can be cached as immutable. Without ``t`` the response must be revalidated.
The ETag answers ``If-None-Match`` with a 304 either way.
"""

import email.utils
import os
from pathlib import Path
from urllib.parse import quote

from fastapi import Request
from fastapi.responses import FileResponse, Response

IMMUTABLE = "private, max-age=31536000, immutable"
REVALIDATE = "private, no-cache"


def _etag_matches(request: Request, etag: str) -> bool:
    header = request.headers.get("if-none-match")
    if not header:
        return False
    return any(tag.strip().removeprefix("W/") == etag for tag in header.split(","))


def content_disposition(kind: str, filename: str) -> str:
    """``inline; filename="…"`` with an RFC 5987 fallback for names that are not ASCII."""
    ascii_name = filename.encode("ascii", "replace").decode().replace('"', "'")
    return f"{kind}; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(filename)}"


def cached_file(
    request: Request,
    path: Path,
    *,
    etag: str | None = None,
    media_type: str | None = None,
    versioned: bool = False,
    download_name: str | None = None,
    inline_name: str | None = None,
) -> Response:
    st = path.stat()
    tag = f'"{etag or f"{st.st_mtime_ns:x}-{st.st_size:x}"}"'
    headers = {"ETag": tag, "Cache-Control": IMMUTABLE if versioned else REVALIDATE, "Last-Modified": email.utils.formatdate(st.st_mtime, usegmt=True)}
    if download_name:
        headers["Content-Disposition"] = content_disposition("attachment", download_name)
    elif inline_name:
        headers["Content-Disposition"] = content_disposition("inline", inline_name)
    if _etag_matches(request, tag):
        return Response(status_code=304, headers=headers)
    return FileResponse(path, media_type=media_type, headers=headers, stat_result=os.stat(path))
