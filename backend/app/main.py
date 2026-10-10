"""FastAPI application entrypoint for QueryMind AI."""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse

from app.api import (
    analytics,
    auth,
    connections,
    conversations,
    health,
    history,
    query,
    saved_queries,
    settings as settings_api,
    uploads,
)
from app.core.config import settings
from app.core.errors import (
    ApiError,
    api_error_handler,
    unhandled_error_handler,
    validation_error_handler,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("querymind")

MAX_BODY_BYTES = 2_000_000  # 2 MB request cap (CSV uploads use their own route limits)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    problems = settings.validate_for_runtime()
    if problems:
        for p in problems:
            logger.error("Configuration problem: %s", p)
        if settings.is_production:
            raise RuntimeError("Fatal configuration errors: " + "; ".join(problems))
    # Verify the metadata database is reachable at startup (fail loudly).
    try:
        from sqlalchemy import text

        from app.db.session import get_engine

        with get_engine().connect() as conn:
            conn.execute(text("SELECT 1"))
        logger.info("Metadata database connection OK")
    except Exception as exc:
        logger.error("Metadata database unreachable: %s", exc.__class__.__name__)
        if settings.is_production:
            raise
    yield


def create_app() -> FastAPI:
    app = FastAPI(
        title="QueryMind AI",
        description="Natural Language to SQL Intelligence Platform",
        version="1.0.0",
        lifespan=lifespan,
        docs_url="/api/docs" if settings.app_env != "production" else None,
        openapi_url="/api/openapi.json" if settings.app_env != "production" else None,
    )

    app.add_middleware(GZipMiddleware, minimum_size=1000)

    @app.middleware("http")
    async def ensure_csrf_cookie(request: Request, call_next):
        """Issue a readable CSRF cookie on the first response (double-submit)."""
        from app.core.security import csrf_cookie_kwargs, new_csrf_token

        response = await call_next(request)
        if settings.csrf_cookie not in request.cookies:
            response.set_cookie(
                settings.csrf_cookie,
                new_csrf_token(),
                **csrf_cookie_kwargs(),
            )
        return response
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[settings.frontend_origin],
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Content-Type", "X-CSRF-Token", "X-Requested-With"],
        expose_headers=["Content-Disposition"],
    )

    @app.middleware("http")
    async def request_limits(request: Request, call_next):
        if request.method in ("POST", "PATCH", "PUT"):
            length = request.headers.get("content-length")
            if length and length.isdigit() and int(length) > MAX_BODY_BYTES:
                if "/api/uploads" not in request.url.path:
                    return JSONResponse(
                        status_code=413,
                        content={
                            "success": False,
                            "error": {
                                "code": "payload_too_large",
                                "message": "Request body is too large.",
                            },
                        },
                    )
        return await call_next(request)

    app.add_exception_handler(ApiError, api_error_handler)
    app.add_exception_handler(RequestValidationError, validation_error_handler)
    app.add_exception_handler(Exception, unhandled_error_handler)

    from fastapi import Depends

    from app.core.deps import enforce_csrf

    csrf = [Depends(enforce_csrf)]

    app.include_router(health.router, prefix="/api/health", tags=["health"])
    app.include_router(auth.router, prefix="/api/auth", tags=["auth"], dependencies=csrf)
    app.include_router(connections.router, prefix="/api/connections", tags=["connections"], dependencies=csrf)
    app.include_router(query.router, prefix="/api/query", tags=["query"], dependencies=csrf)
    app.include_router(history.router, prefix="/api/history", tags=["history"], dependencies=csrf)
    app.include_router(saved_queries.router, prefix="/api/saved-queries", tags=["saved-queries"], dependencies=csrf)
    app.include_router(conversations.router, prefix="/api/conversations", tags=["conversations"], dependencies=csrf)
    app.include_router(analytics.router, prefix="/api/analytics", tags=["analytics"], dependencies=csrf)
    app.include_router(settings_api.router, prefix="/api/settings", tags=["settings"], dependencies=csrf)
    app.include_router(uploads.router, prefix="/api/uploads", tags=["uploads"], dependencies=csrf)

    return app


app = create_app()


if __name__ == "__main__":  # pragma: no cover
    import uvicorn

    port = int(os.environ.get("PORT", "8001"))
    uvicorn.run("app.main:app", host="127.0.0.1", port=port, reload=settings.app_env == "development")
