"""Единый формат ошибок API.

Любая ошибка возвращается в виде:

    {"error": {"code": "VALIDATION_ERROR", "message": "...", "fields": {"email": ["INVALID"]}}}

`code` — стабильный машинный код (фронтенд переводит его на язык интерфейса).
`message` — техническое описание для разработчика, не для показа пользователю.
`fields` — только для ошибок валидации: поле -> список кодов ошибок.
"""

import logging
from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger(__name__)


class ErrorCode:
    VALIDATION_ERROR = "VALIDATION_ERROR"
    BAD_REQUEST = "BAD_REQUEST"
    UNAUTHORIZED = "UNAUTHORIZED"
    FORBIDDEN = "FORBIDDEN"
    NOT_FOUND = "NOT_FOUND"
    METHOD_NOT_ALLOWED = "METHOD_NOT_ALLOWED"
    CONFLICT = "CONFLICT"
    PAYLOAD_TOO_LARGE = "PAYLOAD_TOO_LARGE"
    TOO_MANY_REQUESTS = "TOO_MANY_REQUESTS"
    INTERNAL_ERROR = "INTERNAL_ERROR"


class AppError(Exception):
    """Базовая ошибка приложения. Модули наследуют её в своих exceptions.py."""

    status_code: int = status.HTTP_400_BAD_REQUEST
    code: str = ErrorCode.BAD_REQUEST
    message: str = "Bad request"

    def __init__(
        self,
        message: str | None = None,
        *,
        code: str | None = None,
        status_code: int | None = None,
        fields: dict[str, list[str]] | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        self.message = message or self.message
        self.code = code or self.code
        self.status_code = status_code or self.status_code
        self.fields = fields
        self.headers = headers
        super().__init__(self.message)


class NotFoundError(AppError):
    status_code = status.HTTP_404_NOT_FOUND
    code = ErrorCode.NOT_FOUND
    message = "Resource not found"


class ForbiddenError(AppError):
    status_code = status.HTTP_403_FORBIDDEN
    code = ErrorCode.FORBIDDEN
    message = "Access denied"


class UnauthorizedError(AppError):
    status_code = status.HTTP_401_UNAUTHORIZED
    code = ErrorCode.UNAUTHORIZED
    message = "Authentication required"


class ConflictError(AppError):
    status_code = status.HTTP_409_CONFLICT
    code = ErrorCode.CONFLICT
    message = "Conflict"


class TooManyRequestsError(AppError):
    status_code = status.HTTP_429_TOO_MANY_REQUESTS
    code = ErrorCode.TOO_MANY_REQUESTS
    message = "Too many requests"


def error_body(code: str, message: str, fields: dict[str, list[str]] | None = None) -> dict[str, Any]:
    error: dict[str, Any] = {"code": code, "message": message}
    if fields:
        error["fields"] = fields
    return {"error": error}


_HTTP_STATUS_CODES = {
    400: ErrorCode.BAD_REQUEST,
    401: ErrorCode.UNAUTHORIZED,
    403: ErrorCode.FORBIDDEN,
    404: ErrorCode.NOT_FOUND,
    405: ErrorCode.METHOD_NOT_ALLOWED,
    409: ErrorCode.CONFLICT,
    413: ErrorCode.PAYLOAD_TOO_LARGE,
    429: ErrorCode.TOO_MANY_REQUESTS,
}

# Коды ошибок валидации Pydantic -> наши коды полей
_VALIDATION_CODES = {
    "missing": "REQUIRED",
    "string_too_short": "TOO_SHORT",
    "string_too_long": "TOO_LONG",
    "too_short": "TOO_SHORT",
    "too_long": "TOO_LONG",
    "greater_than": "TOO_SMALL",
    "greater_than_equal": "TOO_SMALL",
    "less_than": "TOO_LARGE",
    "less_than_equal": "TOO_LARGE",
    "value_error": "INVALID",
    "enum": "INVALID_CHOICE",
    "literal_error": "INVALID_CHOICE",
    "extra_forbidden": "NOT_ALLOWED",
}


def _field_name(loc: tuple[Any, ...]) -> str:
    # loc выглядит как ("body", "email") или ("query", "page"); источник отбрасываем
    parts = [str(part) for part in loc[1:]] if len(loc) > 1 else [str(part) for part in loc]
    return ".".join(parts) or "__root__"


async def app_error_handler(_: Request, exc: AppError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content=error_body(exc.code, exc.message, exc.fields),
        headers=exc.headers,
    )


async def validation_error_handler(_: Request, exc: RequestValidationError) -> JSONResponse:
    fields: dict[str, list[str]] = {}
    for err in exc.errors():
        name = _field_name(tuple(err.get("loc", ())))
        code = _VALIDATION_CODES.get(err.get("type", ""), "INVALID")
        fields.setdefault(name, [])
        if code not in fields[name]:
            fields[name].append(code)
    return JSONResponse(
        status_code=422,
        content=error_body(ErrorCode.VALIDATION_ERROR, "Request validation failed", fields),
    )


async def http_error_handler(_: Request, exc: StarletteHTTPException) -> JSONResponse:
    code = _HTTP_STATUS_CODES.get(exc.status_code, ErrorCode.BAD_REQUEST)
    message = exc.detail if isinstance(exc.detail, str) else code
    return JSONResponse(
        status_code=exc.status_code,
        content=error_body(code, message),
        headers=getattr(exc, "headers", None),
    )


async def unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
    # Трассировка — только в лог, пользователю никаких технических деталей
    logger.exception("Unhandled error on %s %s", request.method, request.url.path, exc_info=exc)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content=error_body(ErrorCode.INTERNAL_ERROR, "Internal server error"),
    )


def register_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(AppError, app_error_handler)  # type: ignore[arg-type]
    app.add_exception_handler(RequestValidationError, validation_error_handler)  # type: ignore[arg-type]
    app.add_exception_handler(StarletteHTTPException, http_error_handler)  # type: ignore[arg-type]
    app.add_exception_handler(Exception, unhandled_error_handler)


class FileTooLargeError(AppError):
    status_code = status.HTTP_413_CONTENT_TOO_LARGE
    code = "FILE_TOO_LARGE"
    message = "File is too large"


class UnsupportedFileTypeError(AppError):
    status_code = status.HTTP_415_UNSUPPORTED_MEDIA_TYPE
    code = "UNSUPPORTED_FILE_TYPE"
    message = "Unsupported file type"
