"""Health endpoints: liveness + AI provider status."""

from __future__ import annotations

from fastapi import APIRouter
from sqlalchemy import text

from app.core.config import settings
from app.db.session import get_engine
from app.services.ai_service import build_provider

router = APIRouter()


@router.get("")
def health() -> dict:
    db_ok = False
    try:
        with get_engine().connect() as conn:
            conn.execute(text("SELECT 1"))
        db_ok = True
    except Exception:
        db_ok = False
    return {
        "status": "ok" if db_ok else "degraded",
        "environment": settings.app_env,
        "database": {"connected": db_ok},
    }


@router.get("/ai")
def ai_health() -> dict:
    status = build_provider().status()
    return {
        "status": "ok" if status.available else "unavailable",
        "provider": status.provider,
        "model": status.model,
        "message": status.message,
        "models": status.models,
        "latency_ms": status.latency_ms,
    }
