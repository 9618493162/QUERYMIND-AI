from __future__ import annotations

import logging
import os
import sys
from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine, pool

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.config import settings  # noqa: E402
from app.models import Base  # noqa: E402

config = context.config

if config.config_file_name is not None and not logging.getLogger().handlers:
    # Only a standalone `alembic` CLI run lands here: adopt the ini's console
    # formatting. When a host process (the application at startup, or pytest)
    # already configured logging, never reconfigure it or disable its loggers —
    # a migration must not change how the surrounding process logs.
    fileConfig(config.config_file_name, disable_existing_loggers=False)

# Single source of truth: the exact DATABASE_URL the application connects with
# (psycopg 3 driver, sslmode and every other query parameter preserved).
config.set_main_option("sqlalchemy.url", settings.effective_database_url)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=settings.effective_database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    # Build the engine directly from the effective URL instead of round-tripping
    # through the ini file: the driver and TLS settings cannot be lost, and a
    # '%' inside the password can never break ini interpolation.
    connectable = create_engine(settings.effective_database_url, poolclass=pool.NullPool)
    try:
        with connectable.connect() as connection:
            context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
            with context.begin_transaction():
                context.run_migrations()
    finally:
        connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
