"""Helpers around stored database connections (ownership, credentials, engines)."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import ApiError
from app.models import DatabaseConnection, User
from app.services import crypto
from app.services.schema_service import build_engine


def get_owned_connection(db: Session, user: User, connection_id: str) -> DatabaseConnection:
    conn = db.get(DatabaseConnection, connection_id)
    if conn is None or conn.user_id != user.id:
        raise ApiError(404, "not_found", "Database connection not found.")
    return conn


def connection_password(conn: DatabaseConnection) -> str:
    if not conn.encrypted_credentials:
        return ""
    return crypto.decrypt_secret(conn.encrypted_credentials)


def connection_public(conn: DatabaseConnection) -> dict:
    """Serialize a connection WITHOUT exposing the password."""
    return {
        "id": conn.id,
        "name": conn.name,
        "database_type": conn.database_type,
        "host": conn.host,
        "port": conn.port,
        "database_name": conn.database_name,
        "username": conn.username,
        "ssl_mode": conn.ssl_mode,
        "has_password": bool(conn.encrypted_credentials),
        "created_at": conn.created_at.isoformat() if conn.created_at else None,
        "updated_at": conn.updated_at.isoformat() if conn.updated_at else None,
    }


def engine_for_connection(conn: DatabaseConnection, *, read_only: bool = True):
    password = connection_password(conn)
    return build_engine(
        host=conn.host,
        port=conn.port,
        database=conn.database_name,
        username=conn.username,
        password=password,
        ssl_mode=conn.ssl_mode,
        read_only=read_only,
    )


def list_connections(db: Session, user: User) -> list[DatabaseConnection]:
    return list(
        db.execute(
            select(DatabaseConnection)
            .where(DatabaseConnection.user_id == user.id)
            .order_by(DatabaseConnection.created_at.desc())
        ).scalars()
    )
