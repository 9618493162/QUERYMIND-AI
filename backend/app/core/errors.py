"""Consistent error responses for the API."""

from __future__ import annotations

from typing import Any

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse


class ApiError(Exception):
    """Application error carrying an HTTP status and machine-readable code."""

    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        details: Any | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = details


def error_body(code: str, message: str, details: Any | None = None) -> dict[str, Any]:
    body: dict[str, Any] = {"success": False, "error": {"code": code, "message": message}}
    if details is not None:
        body["error"]["details"] = details
    return body


async def api_error_handler(_request: Request, exc: ApiError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content=error_body(exc.code, exc.message, exc.details),
    )


async def validation_error_handler(_request: Request, exc: RequestValidationError) -> JSONResponse:
    """Return validation failures in the same error envelope as other errors."""
    details = []
    for err in exc.errors():
        loc = ".".join(str(p) for p in err.get("loc", []) if p != "body")
        details.append({"field": loc or None, "message": err.get("msg", "Invalid value")})
    message = details[0]["message"] if details else "Request validation failed."
    return JSONResponse(
        status_code=422,
        content=error_body("validation_error", message, details),
    )


async def unhandled_error_handler(_request: Request, exc: Exception) -> JSONResponse:
    # Never leak stack traces or credentials to end users.
    return JSONResponse(
        status_code=500,
        content=error_body("internal_error", "An unexpected error occurred. Please try again."),
    )
