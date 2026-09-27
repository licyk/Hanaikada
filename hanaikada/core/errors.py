"""Domain exceptions shared by the API and the command line."""

from typing import Any


class HanaikadaError(Exception):
    """Base class for every error the wrappers translate."""

    code = "internal_error"
    http_status = 500
    exit_code = 1

    def __init__(self, message: str, detail: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.detail = detail or {}


class NotFoundError(HanaikadaError):
    """A requested object does not exist."""

    code = "not_found"
    http_status = 404
    exit_code = 2


class ConflictError(HanaikadaError):
    """The target already exists, or the object is in a state that forbids the operation."""

    code = "conflict"
    http_status = 409
    exit_code = 3


class IndexBusyError(ConflictError):
    """A full rebuild of the same root is already running."""

    code = "index_busy"


class InvalidPathError(HanaikadaError):
    """A path is outside its root, or a name is not allowed."""

    code = "invalid_path"
    http_status = 400
    exit_code = 4


class ValidationError(HanaikadaError):
    """An input value is not acceptable."""

    code = "invalid_input"
    http_status = 400
    exit_code = 4


class UnsupportedFileError(ValidationError):
    """The file is not an image Hanaikada can read."""

    code = "unsupported_file"
