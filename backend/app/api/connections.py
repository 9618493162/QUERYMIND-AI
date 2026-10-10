"""Database connection management: CRUD, test, schema inspection."""

from __future__ import annotations

import time

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import delete, select, text as sql_text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.deps import get_current_user
from app.core.errors import ApiError
from app.core.rate_limit import rate_limit
from app.db.session import get_db
from app.models import DatabaseConnection, User
from app.schemas import ConnectionIn, ConnectionOut, TestConnectionIn
from app.services import crypto, connection_service, schema_service
from app.services.db_errors import friendly_connection_error

router = APIRouter()


@router.get("")
def list_connections(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    rows = connection_service.list_connections(db, user)
    return {"success": True, "items": [connection_service.connection_public(c) for c in rows]}


@router.post("", status_code=201)
def create_connection(
    payload: ConnectionIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    if payload.database_type != "postgresql":
        raise ApiError(400, "unsupported_database", "Only PostgreSQL databases are supported right now.")
    available, reason = crypto.encryption_available()
    if not available:
        raise ApiError(503, "encryption_not_configured", reason or "ENCRYPTION_KEY is not configured.")
    schema_service.assert_connection_allowed(payload.host)

    existing = db.execute(
        select(DatabaseConnection).where(
            DatabaseConnection.user_id == user.id,
            DatabaseConnection.name == payload.name.strip(),
        )
    ).scalar_one_or_none()
    if existing is not None:
        raise ApiError(409, "name_taken", "A connection with this name already exists.")

    conn = DatabaseConnection(
        user_id=user.id,
        name=payload.name.strip(),
        database_type=payload.database_type,
        host=payload.host.strip(),
        port=payload.port,
        database_name=payload.database_name.strip(),
        username=payload.username.strip(),
        encrypted_credentials=crypto.encrypt_secret(payload.password) if payload.password else None,
        ssl_mode=payload.ssl_mode,
    )
    db.add(conn)
    db.commit()  # visible to the immediate follow-up schema request
    return {"success": True, "connection": connection_service.connection_public(conn)}


@router.post("/test")
def test_connection(payload: TestConnectionIn, request: Request, user: User = Depends(get_current_user)) -> dict:
    rate_limit(request, "conn-test", 30)
    if payload.database_type != "postgresql":
        raise ApiError(400, "unsupported_database", "Only PostgreSQL databases are supported right now.")
    schema_service.assert_connection_allowed(payload.host)

    started = time.perf_counter()
    engine = schema_service.build_engine(
        host=payload.host,
        port=payload.port,
        database=payload.database_name,
        username=payload.username,
        password=payload.password,
        ssl_mode=payload.ssl_mode,
        read_only=False,
    )
    try:
        with engine.connect() as conn:
            version = conn.execute(sql_text("SHOW server_version")).scalar_one()
            conn.execute(sql_text("SELECT 1"))
    except Exception as exc:
        return {
            "success": False,
            "message": _friendly_connection_error(exc, payload.host, payload.port),
            "server_version": None,
            "latency_ms": int((time.perf_counter() - started) * 1000),
        }
    finally:
        engine.dispose()

    return {
        "success": True,
        "message": "Connection succeeded.",
        "server_version": str(version),
        "latency_ms": int((time.perf_counter() - started) * 1000),
    }


def _friendly_connection_error(exc: Exception, host: str, port: int) -> str:
    message = friendly_connection_error(exc, host, port)
    lowered = str(exc).lower()
    if "ssl" in lowered and "authentication" not in lowered:
        return "TLS negotiation failed. Adjust the SSL mode setting."
    if "role" in lowered and "does not exist" in lowered:
        return "The database role does not exist on the server."
    return message


@router.get("/{connection_id}")
def get_connection(
    connection_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    conn = connection_service.get_owned_connection(db, user, connection_id)
    return {"success": True, "connection": connection_service.connection_public(conn)}


@router.delete("/{connection_id}")
def delete_connection(
    connection_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    conn = connection_service.get_owned_connection(db, user, connection_id)
    db.delete(conn)
    schema_service.invalidate(connection_id)
    db.commit()
    return {"success": True}


@router.get("/{connection_id}/schema")
def get_connection_schema(
    connection_id: str,
    refresh: bool = Query(default=False),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    conn = connection_service.get_owned_connection(db, user, connection_id)
    engine = connection_service.engine_for_connection(conn, read_only=True)
    try:
        info = schema_service.get_schema(engine, connection_id=connection_id, refresh=refresh)
    finally:
        engine.dispose()
    payload = info.to_dict()
    payload["success"] = True
    payload["cached"] = not refresh
    return payload
