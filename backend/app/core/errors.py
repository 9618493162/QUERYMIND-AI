"""Consistent error responses for the API, plus safe server-side logging.

Two guarantees:

* the response envelope never leaks internal detail (no stack traces, no
  credentials, no SQL parameters), and
* server-side exception logging is *structured* (one JSON object per event with
  a request id) and **redacted**: passwords, credentials, connection strings,
  tokens, cookies and SQL parameters are masked before anything is written.

Redaction is applied to the exception message *and* to the formatted traceback,
because a driver exception can embed bound parameters in its message.
"""

from __future__ import annotations

import json
import logging
import re
import traceback
from typing import Any

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

logger = logging.getLogger("querymind.errors")

MAX_LOG_CHARS = 8000

_SECRET_KEY = r"password|passwd|pwd|secret|token|api[_-]?key|authorization|csrf|session[_-]?id"

_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    # key=value / key: value  ->  key=***
    (
        re.compile(
            rf"(?i)\b({_SECRET_KEY})\b\s*[=:]\s*(\"[^\"]*\"|'[^']*'|[^\s,;)\]]+)"
        ),
        r"\1=***",
    ),
    # SQLAlchemy renders bound values as [parameters: (...)] (possibly multiline)
    (re.compile(r"(?is)\[parameters:.*?\]"), "[parameters: ***]"),
    (re.compile(r"(?is)\bparameters\s*[:=]\s*\(.*?\)\s*$", re.MULTILINE), "parameters=***"),
    # postgresql(+driver)://user:password@host
    (re.compile(r"(?i)\b([a-z0-9+]+://[^:/@\s]+):[^@\s]+@"), r"\1:***@"),
    # Double-submit CSRF header echoed in a log line
    (re.compile(r"(?i)\bx-csrf-token\b\s*[:=]\s*\S+"), "X-CSRF-Token=***"),
]


def redact(value: str, *, limit: int = MAX_LOG_CHARS) -> str:
    """Mask secrets and bound SQL parameters in a log string."""
    out = value or ""
    for pattern, replacement in _PATTERNS:
        out = pattern.sub(replacement, out)
    if len(out) > limit:
        out = f"{out[:limit]}...(truncated)"
    return out


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


async def unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
    """Log unhandled exceptions in a structured, redacted form; never leak them.

    The full traceback goes to the server log (redacted), while the client only
    receives a generic message.
    """
    request_id = getattr(request.state, "request_id", None)
    formatted = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    logger.error(
        json.dumps(
            {
                "event": "unhandled_exception",
                "request_id": request_id,
                # Path only: a query string could contain user data.
                "path": request.url.path,
                "method": request.method,
                "error_type": type(exc).__name__,
                "message": redact(str(exc), limit=1000),
                "traceback": redact(formatted),
            },
            separators=(",", ":"),
            default=str,
        )
    )
    return JSONResponse(
        status_code=500,
        content=error_body("internal_error", "An unexpected error occurred. Please try again."),
    )
