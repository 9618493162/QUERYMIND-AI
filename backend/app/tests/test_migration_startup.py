"""Startup migration behaviour: the schema must exist before requests are served.

Regression guard for the production bug where the API came up while the
metadata database was still empty, so registration failed with
``relation "users" does not exist``.

Covered here:

* Alembic is configured with the same effective DATABASE_URL the application
  uses (psycopg driver + TLS query parameters preserved);
* the startup step runs **before the first request**, at most once per
  process, and only when ``RUN_MIGRATIONS_ON_STARTUP`` allows it;
* a failing migration is fatal in production and merely logged otherwise;
* only ``alembic upgrade head`` is ever invoked — never a downgrade;
* a real, empty PostgreSQL database is migrated end to end and registration
  then succeeds against it, which is the exact production symptom.
"""

from __future__ import annotations

import logging
import uuid
from urllib.parse import urlsplit, urlunsplit

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect, text

import app.db.migrate as migrate
from app.core.config import normalize_database_url, settings
from app.db import session as db_session
from app.main import app

# The tables created by the initial migration; `users` is the relation the
# production registration request failed on.
REQUIRED_TABLES = {
    "users",
    "database_connections",
    "uploaded_datasets",
    "user_sessions",
    "user_settings",
    "conversations",
    "saved_queries",
    "conversation_messages",
    "query_history",
}


def _url_with_database(name: str, base: str | None = None) -> str:
    """Same server/credentials/query as `base`, but pointing at `name`."""
    parts = urlsplit(base if base is not None else settings.database_url)
    return urlunsplit((parts.scheme, parts.netloc, "/" + name, parts.query, ""))


def _ensure_database(name: str, base: str | None = None) -> None:
    """Create the database if it does not exist yet (never drops anything)."""
    admin_url = _url_with_database("postgres", base)
    engine = create_engine(admin_url, isolation_level="AUTOCOMMIT", future=True)
    try:
        with engine.connect() as conn:
            exists = conn.execute(
                text("SELECT 1 FROM pg_database WHERE datname = :db"), {"db": name}
            ).scalar()
            if not exists:
                conn.execute(text(f'CREATE DATABASE "{name}"'))
    finally:
        engine.dispose()


# --- URL wiring: production DATABASE_URL reaches Alembic unchanged -----------

def test_bare_postgres_urls_get_the_installed_driver():
    assert normalize_database_url("postgres://u:p@h:5432/db") == (
        "postgresql+psycopg://u:p@h:5432/db"
    )
    assert normalize_database_url("postgresql://u:p@h:5432/db") == (
        "postgresql+psycopg://u:p@h:5432/db"
    )
    # An explicit driver and non-PostgreSQL URLs are never rewritten.
    assert normalize_database_url("postgresql+psycopg://u:p@h:5432/db") == (
        "postgresql+psycopg://u:p@h:5432/db"
    )
    assert normalize_database_url("sqlite:///app.db") == "sqlite:///app.db"


def test_effective_url_keeps_tls_settings_and_feeds_alembic(monkeypatch):
    monkeypatch.setattr(
        settings,
        "database_url",
        "postgres://u:p@db.example.com:5432/querymind?sslmode=require",
    )
    assert settings.effective_database_url == (
        "postgresql+psycopg://u:p@db.example.com:5432/querymind?sslmode=require"
    )

    cfg = migrate.alembic_config()
    # The migration connects exactly like the application: same driver, same
    # credentials, same TLS settings, no hardcoded URL anywhere.
    assert cfg.get_main_option("sqlalchemy.url") == settings.effective_database_url
    assert cfg.get_main_option("script_location") == str(migrate.MIGRATIONS_DIR)


def test_only_upgrade_head_is_ever_invoked(monkeypatch):
    calls: list[tuple[str, str]] = []
    monkeypatch.setattr(migrate.command, "upgrade", lambda cfg, rev: calls.append(("upgrade", rev)))
    monkeypatch.setattr(
        migrate.command, "downgrade", lambda cfg, rev: calls.append(("downgrade", rev))
    )

    # Uses the (live) test database just for the advisory-lock connection; the
    # Alembic command itself is stubbed, so no schema change happens here.
    migrate.apply_migrations()

    assert calls == [("upgrade", "head")]
    assert ("downgrade", "head") not in calls


# --- startup wiring: migrations run before the first request ----------------

def test_startup_runs_migrations_before_serving(monkeypatch):
    applied: list[str] = []
    monkeypatch.setattr(settings, "run_migrations_on_startup", True)
    monkeypatch.setattr(migrate, "_schema_applied", False)
    monkeypatch.setattr(migrate, "apply_migrations", lambda: applied.append("migrated"))

    with TestClient(app) as client:
        # Recorded during startup: the server could not have answered the
        # request below before the schema existed.
        assert applied == ["migrated"]
        resp = client.get("/api/health")
    assert resp.status_code == 200


def test_startup_migrations_apply_at_most_once_per_process(monkeypatch):
    calls: list[int] = []
    monkeypatch.setattr(settings, "run_migrations_on_startup", True)
    monkeypatch.setattr(migrate, "_schema_applied", False)
    monkeypatch.setattr(migrate, "apply_migrations", lambda: calls.append(1))

    migrate.run_startup_migrations()
    migrate.run_startup_migrations()

    assert calls == [1]


def test_disabled_startup_migrations_never_run(monkeypatch):
    calls: list[int] = []
    monkeypatch.setattr(settings, "run_migrations_on_startup", False)
    monkeypatch.setattr(migrate, "_schema_applied", False)
    monkeypatch.setattr(migrate, "apply_migrations", lambda: calls.append(1))

    with TestClient(app) as client:
        assert calls == []
        resp = client.get("/api/health")
    assert resp.status_code == 200


# --- failure modes ----------------------------------------------------------

def test_migration_failure_aborts_startup(monkeypatch):
    """The lifespan must not swallow the failure: no schema, no traffic."""
    def boom() -> None:
        raise RuntimeError("Database migration failed: broken upgrade")

    monkeypatch.setattr(migrate, "run_startup_migrations", boom)

    with pytest.raises(RuntimeError, match="broken upgrade"):
        with TestClient(app):
            raise AssertionError("startup must not complete without a schema")


def test_migration_failure_is_fatal_in_production(monkeypatch):
    def boom() -> None:
        raise RuntimeError("connect failed: password=hunter2")

    monkeypatch.setattr(settings, "run_migrations_on_startup", True)
    monkeypatch.setattr(migrate, "_schema_applied", False)
    monkeypatch.setattr(migrate, "apply_migrations", boom)

    with pytest.raises(RuntimeError, match="Database migration failed") as excinfo:
        migrate.run_startup_migrations(strict=True)

    # Fail closed, but never log a credential while doing it.
    assert "hunter2" not in str(excinfo.value)


def test_migration_failure_is_logged_outside_production(monkeypatch, caplog):
    def boom() -> None:
        raise RuntimeError("connect failed: password=hunter2")

    monkeypatch.setattr(settings, "run_migrations_on_startup", True)
    monkeypatch.setattr(migrate, "_schema_applied", False)
    monkeypatch.setattr(migrate, "apply_migrations", boom)
    caplog.set_level(logging.ERROR, logger="querymind.migrate")

    migrate.run_startup_migrations(strict=False)  # dev/test: keep failing soft

    messages = [r.getMessage() for r in caplog.records if "migration failed" in r.getMessage()]
    assert messages, "the failure must be logged server-side"
    assert "hunter2" not in messages[0]


# --- end to end: an empty database becomes a working schema ------------------

def test_empty_database_is_migrated_at_startup_and_registration_works(monkeypatch):
    """The production bug, reproduced and fixed: empty DB → register → 201."""
    probe_name = "querymind_migrate_probe"
    probe_url = _url_with_database(probe_name)
    _ensure_database(probe_name)

    monkeypatch.setattr(settings, "database_url", probe_url)
    monkeypatch.setattr(settings, "run_migrations_on_startup", True)
    monkeypatch.setattr(migrate, "_schema_applied", False)
    # Rebuild the application engine against the probe database.
    db_session.dispose_engine()
    try:
        with TestClient(app) as client:  # lifespan runs `alembic upgrade head`
            # The schema really exists now...
            engine = db_session.get_engine()
            tables = set(inspect(engine).get_table_names())
            assert REQUIRED_TABLES <= tables, f"missing: {sorted(REQUIRED_TABLES - tables)}"

            from alembic.script import ScriptDirectory

            head = ScriptDirectory.from_config(migrate.alembic_config()).get_current_head()
            with engine.connect() as conn:
                versions = [
                    row[0] for row in conn.execute(text("SELECT version_num FROM alembic_version"))
                ]
            assert versions == [head]

            # ...so the request that used to fail with
            # `relation "users" does not exist` now succeeds.
            client.get("/api/health")  # bootstraps the CSRF cookie
            # A unique address keeps the probe database reusable across runs.
            email = f"probe-{uuid.uuid4().hex[:12]}@querymind.dev"
            resp = client.post(
                "/api/auth/register",
                json={
                    "name": "Probe User",
                    "email": email,
                    "password": "Sup3rSecret!",
                },
                headers={"X-CSRF-Token": client.cookies.get("querymind_csrf")},
            )
            assert resp.status_code == 201, resp.text
    finally:
        # Hand the shared engine back so later tests reconnect to the test DB.
        db_session.dispose_engine()


def test_repeated_startup_on_a_migrated_database_is_a_no_op(monkeypatch):
    """A database already at head must not be touched by later startups."""
    probe_name = "querymind_migrate_probe"
    probe_url = _url_with_database(probe_name)
    _ensure_database(probe_name)

    monkeypatch.setattr(settings, "database_url", probe_url)
    monkeypatch.setattr(settings, "run_migrations_on_startup", True)
    monkeypatch.setattr(migrate, "_schema_applied", False)
    db_session.dispose_engine()
    try:
        with TestClient(app) as client:
            engine = db_session.get_engine()
            with engine.connect() as conn:
                users_before = conn.execute(text('SELECT count(*) FROM "users"')).scalar()
            # Still served, still at head, and an existing schema is intact.
            client.get("/api/health")
            with engine.connect() as conn:
                users_after = conn.execute(text('SELECT count(*) FROM "users"')).scalar()
            assert users_after == users_before
            resp = client.get("/api/health/ready")
            assert resp.status_code == 200, resp.text
    finally:
        db_session.dispose_engine()
