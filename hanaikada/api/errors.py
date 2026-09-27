"""Map domain exceptions onto one JSON error shape."""

from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import Field

from hanaikada.core.errors import HanaikadaError
from hanaikada.core.record import Record


class ErrorResponse(Record):
    code: str
    message: str
    detail: dict[str, Any] = Field(default_factory=dict)


def error_response(status: int, code: str, message: str, detail: dict[str, Any] | None = None, headers: dict[str, str] | None = None) -> JSONResponse:
    return JSONResponse(status_code=status, content={"code": code, "message": message, "detail": detail or {}}, headers=headers)


async def _domain_error(_request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, HanaikadaError)
    return error_response(exc.http_status, exc.code, exc.message, exc.detail)


def install_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(HanaikadaError, _domain_error)


# Declared on routes so the generated client knows the error shape.
ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    400: {"model": ErrorResponse},
    404: {"model": ErrorResponse},
    403: {"model": ErrorResponse},
    409: {"model": ErrorResponse},
}
