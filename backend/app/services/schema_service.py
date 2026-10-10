"""Schema inspection of the user's connected analytical database.

Reads metadata only (information_schema / pg_catalog); never loads table data.
Results are cached briefly per connection with an explicit refresh path.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from app.core.errors import ApiError
from app.security.network_policy import assert_destination_allowed
from app.services.db_errors import friendly_connection_error, is_unreachable

CACHE_TTL_SECONDS = 300

_cache: dict[str, tuple[float, dict[str, Any]]] = {}
_cache_lock = threading.Lock()


def build_engine(
    *,
    host: str,
    port: int,
    database: str,
    username: str,
    password: str,
    ssl_mode: str = "prefer",
    connect_timeout: int = 5,
    read_only: bool = False,
    statement_timeout_ms: int = 15000,
) -> Engine:
    from urllib.parse import quote_plus

    url = (
        f"postgresql+psycopg://{quote_plus(username)}:{quote_plus(password)}"
        f"@{host}:{port}/{quote_plus(database)}"
    )
    # Only SERVER-side GUCs may go into `options`; libpq client parameters
    # (connect_timeout, sslmode, ...) must be passed as connect arguments.
    options = [f"-c statement_timeout={int(statement_timeout_ms)}"]
    if read_only:
        options.append("-c default_transaction_read_only=on")
    connect_args: dict[str, object] = {
        "options": " ".join(options),
        "connect_timeout": connect_timeout,
        "sslmode": ssl_mode or "prefer",
        "application_name": "querymind",
    }
    return create_engine(
        url,
        poolclass=__import__("sqlalchemy").pool.QueuePool,
        pool_size=3,
        max_overflow=3,
        pool_pre_ping=True,
        pool_recycle=600,
        connect_args=connect_args,
        future=True,
    )


def assert_connection_allowed(host: str) -> None:
    assert_destination_allowed(host)


EXCLUDED_SCHEMAS = {"pg_catalog", "information_schema", "pg_toast"}

SCHEMA_SQL = text(
    """
    SELECT n.nspname AS schema_name,
           c.relname AS object_name,
           c.relkind AS kind
    FROM pg_catalog.pg_class c
    JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
    WHERE n.nspname NOT IN ('pg_catalog', 'information_schema', 'pg_toast')
      AND c.relkind IN ('r', 'p', 'v', 'm', 'f')
    ORDER BY 1, 2
    """
)

COLUMNS_SQL = text(
    """
    SELECT table_schema, table_name, column_name, data_type, udt_name,
           is_nullable, ordinal_position
    FROM information_schema.columns
    WHERE table_schema NOT IN ('pg_catalog', 'information_schema')
    ORDER BY table_schema, table_name, ordinal_position
    """
)

PK_SQL = text(
    """
    SELECT tc.table_schema, tc.table_name, kcu.column_name
    FROM information_schema.table_constraints tc
    JOIN information_schema.key_column_usage kcu
      ON kcu.constraint_name = tc.constraint_name AND kcu.table_schema = tc.table_schema
    WHERE tc.constraint_type = 'PRIMARY KEY'
      AND tc.table_schema NOT IN ('pg_catalog', 'information_schema')
    """
)

FK_SQL = text(
    """
    SELECT tc.table_schema, tc.table_name, kcu.column_name,
           ccu.table_schema AS ref_schema, ccu.table_name AS ref_table, ccu.column_name AS ref_column
    FROM information_schema.table_constraints tc
    JOIN information_schema.key_column_usage kcu
      ON kcu.constraint_name = tc.constraint_name AND kcu.table_schema = tc.table_schema
    JOIN information_schema.constraint_column_usage ccu
      ON ccu.constraint_name = tc.constraint_name AND ccu.table_schema = tc.table_schema
    WHERE tc.constraint_type = 'FOREIGN KEY'
      AND tc.table_schema NOT IN ('pg_catalog', 'information_schema')
    """
)


@dataclass
class SchemaInfo:
    schemas: list[str] = field(default_factory=list)
    tables: list[dict[str, Any]] = field(default_factory=list)
    relationships: list[dict[str, Any]] = field(default_factory=list)
    fetched_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schemas": self.schemas,
            "tables": self.tables,
            "relationships": self.relationships,
            "fetched_at": self.fetched_at,
        }

    def allowlist(self) -> dict[str, set[str]]:
        out: dict[str, set[str]] = {}
        for t in self.tables:
            out.setdefault(t["schema"], set()).add(t["name"])
        return out

    def schema_set(self) -> set[str]:
        return {t["schema"] for t in self.tables}

    def prompt_context(self, max_tables: int = 40) -> str:
        lines: list[str] = []
        for t in self.tables[:max_tables]:
            cols = ", ".join(
                f"{c['name']} {c['type']}" + (" PK" if c.get("pk") else "")
                for c in t["columns"]
            )
            kind = "view" if t.get("kind") == "view" else "table"
            lines.append(f"{kind} {t['schema']}.{t['name']}: {cols}")
        if self.relationships:
            lines.append("Foreign keys:")
            for r in self.relationships:
                lines.append(
                    f"  {r['schema']}.{r['table']}.{r['column']} -> "
                    f"{r['ref_schema']}.{r['ref_table']}.{r['ref_column']}"
                )
        if len(self.tables) > max_tables:
            lines.append(f"... ({len(self.tables) - max_tables} more tables omitted)")
        return "\n".join(lines) if lines else "(no tables found)"


def _load_schema(engine: Engine) -> SchemaInfo:
    info = SchemaInfo()
    with engine.connect() as conn:
        objects = {f"{r[0]}.{r[1]}": r[2] for r in conn.execute(SCHEMA_SQL).all()}
        columns: dict[str, list[dict[str, Any]]] = {}
        schemas: set[str] = set()
        for schema, table, col, data_type, udt, nullable, _pos in conn.execute(COLUMNS_SQL).all():
            schemas.add(schema)
            columns.setdefault(f"{schema}.{table}", []).append(
                {
                    "name": col,
                    "type": data_type if data_type else udt,
                    "udt": udt,
                    "nullable": nullable == "YES",
                }
            )
        pks: set[tuple[str, str, str]] = set()
        for schema, table, col in conn.execute(PK_SQL).all():
            pks.add((schema, table, col))
        for row in conn.execute(FK_SQL).all():
            schema, table, col, ref_schema, ref_table, ref_col = row
            info.relationships.append(
                {
                    "schema": schema,
                    "table": table,
                    "column": col,
                    "ref_schema": ref_schema,
                    "ref_table": ref_table,
                    "ref_column": ref_col,
                }
            )

    for key, kind in objects.items():
        schema, name = key.split(".", 1)
        cols = columns.get(key, [])
        for c in cols:
            c["pk"] = (schema, name, c["name"]) in pks
        info.tables.append(
            {
                "schema": schema,
                "name": name,
                "kind": "view" if kind in {"v", "m"} else "table",
                "columns": cols,
            }
        )
        info.schemas.append(schema)
    info.schemas = sorted(set(info.schemas))
    info.tables.sort(key=lambda t: (t["schema"], t["name"]))
    return info


def get_schema(engine: Engine, *, connection_id: str, refresh: bool = False) -> SchemaInfo:
    now = time.time()
    with _cache_lock:
        if not refresh and connection_id in _cache:
            ts, cached = _cache[connection_id]
            if now - ts < CACHE_TTL_SECONDS:
                return cached
    try:
        info = _load_schema(engine)
    except ApiError:
        raise
    except Exception as exc:
        # An unreachable / refused / timed-out server is not a schema problem:
        # report it as a connection failure so the user fixes the right thing.
        if is_unreachable(exc):
            host = getattr(engine.url, "host", "unknown")
            port = getattr(engine.url, "port", "")
            raise ApiError(
                502,
                "db_unreachable",
                f"Could not reach the database: {friendly_connection_error(exc, host, port)}",
            ) from exc
        raise ApiError(
            502,
            "schema_inspection_failed",
            f"Could not inspect the database schema: {exc.__class__.__name__}. "
            "Check the connection credentials and that the user has SELECT access.",
        ) from exc
    with _cache_lock:
        _cache[connection_id] = (now, info)
    return info


def invalidate(connection_id: str | None = None) -> None:
    with _cache_lock:
        if connection_id is None:
            _cache.clear()
        else:
            _cache.pop(connection_id, None)
