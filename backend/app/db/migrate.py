"""Explicit startup/release database migration step.

Registration, login and every other endpoint read the metadata database, so
the schema must exist *before* the API serves its first request. Without this
step a freshly provisioned database answers every query with
``relation "users" does not exist``.

Two entry points, both applying exactly ``alembic upgrade head``:

* **Startup** — :func:`run_startup_migrations` is called from the FastAPI
  lifespan, so uvicorn only starts accepting traffic once the schema is in
  place. In production this is fail-closed: if the migration cannot run, the
  process refuses to serve requests instead of serving 500s.
* **Release/CLI** — ``python -m app.db.migrate`` (or the documented
  ``python -m alembic upgrade head``, which uses the very same URL) for a
  deploy runbook that migrates before rolling new code out.

Safety properties:

* **Upgrade only.** The only Alembic command invoked is
  ``command.upgrade(cfg, "head")`` — never ``downgrade``, never a drop.
* **Idempotent.** A database already at head is a no-op, and each process
  applies migrations at most once.
* **Serialised.** Concurrent starts (several uvicorn workers, two containers
  booting together) queue on a PostgreSQL advisory lock instead of racing
  each other's ``CREATE TABLE`` statements.
* **No secrets in logs.** Failure text passes through the shared redactor.
"""

from __future__ import annotations

import logging
import threading
from pathlib import Path

from alembic import command
from alembic.config import Config

from app.core.config import settings
from app.core.errors import redact

logger = logging.getLogger("querymind.migrate")

# Repository layout: <backend>/app/db/migrate.py -> <backend>
BACKEND_DIR = Path(__file__).resolve().parents[2]
ALEMBIC_INI = BACKEND_DIR / "alembic.ini"
MIGRATIONS_DIR = BACKEND_DIR / "alembic"

# Stable, arbitrary key ("QMIG"): all processes of this application serialise
# schema changes through it.
_ADVISORY_LOCK_KEY = 0x514D4947
# Never hang forever behind a stuck lock; fail loudly instead.
_LOCK_TIMEOUT_SQL = "SET lock_timeout = '30s'"

# At most one upgrade per process, and one in-flight upgrade at a time.
_run_lock = threading.Lock()
_schema_applied = False


def alembic_config() -> Config:
    """Programmatic equivalent of ``alembic -c alembic.ini``.

    ``sqlalchemy.url`` is set from the application's effective DATABASE_URL so
    migrations connect exactly like the running application: psycopg 3 driver,
    credentials, ``sslmode`` and every other query parameter preserved.
    """
    cfg = Config(str(ALEMBIC_INI))
    cfg.set_main_option("script_location", str(MIGRATIONS_DIR))
    cfg.set_main_option("sqlalchemy.url", settings.effective_database_url)
    return cfg


def apply_migrations() -> None:
    """Run ``alembic upgrade head`` against ``settings.effective_database_url``.

    Raises on any failure; callers decide whether that is fatal.
    """
    from sqlalchemy import create_engine, text
    from sqlalchemy.pool import NullPool

    url = settings.effective_database_url
    cfg = alembic_config()

    # A dedicated (non-pooled) engine: the session-level advisory lock must
    # live on its own connection and be released when that connection closes.
    lock_engine = create_engine(url, poolclass=NullPool, future=True)
    try:
        if lock_engine.dialect.name != "postgresql":
            # Databases without an advisory lock (tests, SQLite) simply run the
            # upgrade: single-process by construction.
            command.upgrade(cfg, "head")
            return
        with lock_engine.connect().execution_options(isolation_level="AUTOCOMMIT") as lock:
            lock.execute(text(_LOCK_TIMEOUT_SQL))
            lock.execute(text("SELECT pg_advisory_lock(:key)"), {"key": _ADVISORY_LOCK_KEY})
            try:
                command.upgrade(cfg, "head")
            finally:
                lock.execute(
                    text("SELECT pg_advisory_unlock(:key)"), {"key": _ADVISORY_LOCK_KEY}
                )
    finally:
        lock_engine.dispose()


def run_startup_migrations(*, strict: bool | None = None) -> None:
    """Apply pending migrations before the server accepts its first request.

    ``strict`` defaults to the production flag. Production fails closed — an
    exception aborts startup — while development and test keep the
    application's existing fail-soft behaviour for a database that is simply
    not running.
    """
    global _schema_applied
    if not settings.run_migrations_on_startup:
        logger.info(
            "Startup migrations disabled (RUN_MIGRATIONS_ON_STARTUP=false); "
            "run `python -m alembic upgrade head` explicitly."
        )
        return
    if strict is None:
        strict = settings.is_production
    with _run_lock:
        if _schema_applied:
            return
        try:
            apply_migrations()
        except Exception as exc:
            message = f"Database migration failed: {redact(str(exc))}"
            if strict:
                raise RuntimeError(message) from exc
            logger.error(
                "%s (startup continues because this is not production; "
                "database-backed endpoints will fail until it is resolved)",
                message,
            )
            return
        _schema_applied = True
        logger.info("Database schema is up to date (alembic upgrade head).")


if __name__ == "__main__":  # pragma: no cover - explicit release step
    # `python -m app.db.migrate`: always runs (the flag only gates *startup*
    # migrations) and exits non-zero on failure so a deploy pipeline stops.
    logging.basicConfig(level=logging.INFO, format="%(levelname)s [%(name)s] %(message)s")
    apply_migrations()
    logger.info("Migrations applied: database is at head.")
