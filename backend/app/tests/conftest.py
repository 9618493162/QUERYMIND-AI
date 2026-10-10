"""Test configuration.

Uses a SEPARATE PostgreSQL database (querymind_test) so tests never touch
application or production data. Environment is set BEFORE importing the app.
"""

from __future__ import annotations

import os
import pathlib

# --- environment must be configured before any app import -------------------
_BACKEND_DIR = pathlib.Path(__file__).resolve().parents[2]


def _env(name: str, default: str) -> str:
    """Read a setting from the environment, falling back to the local defaults.

    Continuous integration points these at its own service containers; a local
    developer needs no configuration at all because the defaults match the
    ports published by docker-compose.yml.
    """
    value = os.environ.get(name)
    return value if value not in (None, "") else default


# Application metadata database (docker-compose publishes it on host port 5434).
APP_DB = {
    "host": _env("QM_APP_DB_HOST", "localhost"),
    "port": int(_env("QM_APP_DB_PORT", "5434")),
    "database": _env("QM_APP_DB_NAME", "querymind"),
    "username": _env("QM_APP_DB_USER", "app_user"),
    "password": _env("QM_APP_DB_PASSWORD", "app_password_change_me"),
}
TEST_DATABASE = _env("QM_TEST_DB_NAME", "querymind_test")

# The analytics database used for real query execution tests (sample data).
ANALYTICS = {
    "host": _env("QM_ANALYTICS_HOST", "localhost"),
    "port": int(_env("QM_ANALYTICS_PORT", "5433")),
    "database": _env("QM_ANALYTICS_DB", "analytics"),
    "username": _env("QM_ANALYTICS_USER", "analytics_owner"),
    "password": _env("QM_ANALYTICS_PASSWORD", "analytics_password_change_me"),
    "ssl_mode": _env("QM_ANALYTICS_SSLMODE", "disable"),
}


def _dsn(host: str, port: int, database: str, username: str, password: str) -> str:
    from urllib.parse import quote_plus

    return (
        f"postgresql+psycopg://{quote_plus(username)}:{quote_plus(password)}"
        f"@{host}:{port}/{quote_plus(database)}"
    )


os.environ["APP_ENV"] = "test"
os.environ["APP_SECRET_KEY"] = "test-secret-key-not-for-production"
os.environ["DATABASE_URL"] = _dsn(
    APP_DB["host"], APP_DB["port"], TEST_DATABASE, APP_DB["username"], APP_DB["password"]
)
os.environ["FRONTEND_ORIGIN"] = "http://localhost:5173"
os.environ.setdefault("ENCRYPTION_KEY", "test-encryption-key-0123456789abcdef")
os.environ["ALLOW_PRIVATE_DB_HOSTS"] = "true"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import text  # noqa: E402

from app.core.config import settings  # noqa: E402
from app.db.session import dispose_engine, get_engine  # noqa: E402
from app.models import Base  # noqa: E402
from app.main import app  # noqa: E402
from app.core import rate_limit  # noqa: E402

APP_DB_URL = _dsn(APP_DB["host"], APP_DB["port"], "postgres", APP_DB["username"], APP_DB["password"])


def _ensure_test_database() -> None:
    from sqlalchemy import create_engine

    engine = create_engine(APP_DB_URL, isolation_level="AUTOCOMMIT", future=True)
    try:
        with engine.connect() as conn:
            exists = conn.execute(
                text("SELECT 1 FROM pg_database WHERE datname = :db"), {"db": TEST_DATABASE}
            ).scalar()
            if not exists:
                conn.execute(text(f'CREATE DATABASE "{TEST_DATABASE}"'))
    finally:
        engine.dispose()


_ensure_test_database()
dispose_engine()
get_engine().connect().close()

Base.metadata.create_all(get_engine())


@pytest.fixture(autouse=True)
def _clean_tables():
    """Truncate all application tables before each test."""
    engine = get_engine()
    table_names = ", ".join(f'"{t.name}"' for t in Base.metadata.sorted_tables)
    with engine.begin() as conn:
        conn.exec_driver_sql(f"TRUNCATE {table_names} CASCADE")
    rate_limit.reset()
    yield


@pytest.fixture()
def client() -> TestClient:
    with TestClient(app) as c:
        yield c


@pytest.fixture()
def auth_client(client: TestClient) -> TestClient:
    """Registered + logged in client (also bootstraps the CSRF cookie)."""
    client.get("/api/health")
    resp = client.post(
        "/api/auth/register",
        json={"name": "Test User", "email": "tester@querymind.dev", "password": "Sup3rSecret!"},
        headers={"X-CSRF-Token": client.cookies.get("querymind_csrf")},
    )
    assert resp.status_code == 201, resp.text
    return client


def csrf(client: TestClient) -> dict[str, str]:
    token = client.cookies.get("querymind_csrf")
    return {"X-CSRF-Token": token} if token else {}


@pytest.fixture()
def analytics_connection_payload() -> dict:
    return {
        "name": "Sample analytics DB",
        "host": ANALYTICS["host"],
        "port": ANALYTICS["port"],
        "database_name": ANALYTICS["database"],
        "username": ANALYTICS["username"],
        "password": ANALYTICS["password"],
        "ssl_mode": ANALYTICS["ssl_mode"],
    }
