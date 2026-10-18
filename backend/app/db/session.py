"""SQLAlchemy engine/session for the application metadata database."""

from __future__ import annotations

from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings

_engine: Engine | None = None
_SessionLocal: sessionmaker[Session] | None = None


def get_engine() -> Engine:
    global _engine, _SessionLocal
    if _engine is None:
        # Pool sizing is configurable because it is per process: a managed
        # PostgreSQL instance (or a pooler in front of it) caps total
        # connections, so several uvicorn workers multiply this budget.
        # The same effective URL Alembic uses: driver, credentials and sslmode
        # settings are identical for the running server and for migrations.
        _engine = create_engine(
            settings.effective_database_url,
            pool_pre_ping=True,
            pool_size=settings.db_pool_size,
            max_overflow=settings.db_max_overflow,
            pool_timeout=settings.db_pool_timeout_seconds,
            pool_recycle=settings.db_pool_recycle_seconds,
            future=True,
        )
        _SessionLocal = sessionmaker(bind=_engine, autoflush=False, expire_on_commit=False, future=True)
    return _engine


def get_session_factory() -> sessionmaker[Session]:
    get_engine()
    assert _SessionLocal is not None
    return _SessionLocal


def get_db() -> Generator[Session, None, None]:
    """Request-scoped session.

    FastAPI finalizes this dependency AFTER the response has been sent, so the
    trailing commit is only a safety net. Handlers that mutate data MUST call
    ``db.commit()`` themselves before returning, otherwise flushed-but-
    uncommitted rows are invisible to the client's next request (for example
    `POST /api/connections` followed immediately by `GET .../schema`).
    """
    session = get_session_factory()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def dispose_engine() -> None:
    global _engine, _SessionLocal
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _SessionLocal = None
