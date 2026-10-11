"""Health endpoints.

Three deliberately different contracts:

``GET /api/health``
    **Liveness.** Is the process up and serving HTTP? It never touches the
    database, so a slow or restarting database cannot cause an orchestrator to
    kill a perfectly healthy application container.

``GET /api/health/ready``
    **Readiness.** Is the application able to serve requests, i.e. is the
    metadata database reachable? Returns HTTP 503 when it is not, so a load
    balancer / reverse proxy stops routing traffic to this instance without
    restarting it.

``GET /api/health/ai``
    Provider diagnostics for the real model server. This is the *only* endpoint
    that contacts Ollama, and the result is cached briefly so repeated probes
    cannot hammer the model server. It is not used for liveness or readiness.
"""

from __future__ import annotations

import threading
import time

from fastapi import APIRouter, Response
from sqlalchemy import text

from app.core.config import settings
from app.db.session import get_engine
from app.services.ai_service import AIStatus, build_provider

router = APIRouter()

# --- AI provider diagnostics (cached) ---------------------------------------
_ai_status_cache: tuple[float, AIStatus] | None = None
_ai_cache_lock = threading.Lock()


def reset_ai_status_cache() -> None:
    """Clear the cached provider status (used by tests and after a restart)."""
    global _ai_status_cache
    with _ai_cache_lock:
        _ai_status_cache = None


def cached_ai_status() -> AIStatus:
    """Return the provider status, probing Ollama at most once per cache window."""
    global _ai_status_cache
    ttl = settings.ai_health_cache_seconds
    now = time.monotonic()
    if ttl > 0:
        with _ai_cache_lock:
            cached = _ai_status_cache
        if cached is not None and now - cached[0] < ttl:
            return cached[1]

    status = build_provider().status()
    with _ai_cache_lock:
        _ai_status_cache = (time.monotonic(), status)
    return status


# --- endpoints --------------------------------------------------------------

@router.get("")
def health() -> dict:
    """Liveness probe: the process answers. Never depends on the database."""
    return {
        "status": "ok",
        "probe": "liveness",
        "environment": settings.app_env,
    }


@router.get("/ready")
def readiness(response: Response) -> dict:
    """Readiness probe: HTTP 503 while the metadata database is unreachable."""
    db_ok = False
    try:
        with get_engine().connect() as conn:
            conn.execute(text("SELECT 1"))
        db_ok = True
    except Exception:
        db_ok = False

    if not db_ok:
        response.status_code = 503
    return {
        "status": "ok" if db_ok else "unavailable",
        "probe": "readiness",
        "environment": settings.app_env,
        "database": {"connected": db_ok},
    }


@router.get("/ai")
def ai_health() -> dict:
    status = cached_ai_status()
    return {
        "status": "ok" if status.available else "unavailable",
        "provider": status.provider,
        "model": status.model,
        "message": status.message,
        "models": status.models,
        "latency_ms": status.latency_ms,
        "cached_for_seconds": settings.ai_health_cache_seconds,
    }
