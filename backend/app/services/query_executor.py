"""Read-only execution of validated SQL against the selected database.

Defense in depth applied here (in addition to sql_validator):
- destination policy check before connecting
- read-only session (default_transaction_read_only=on) + statement timeout
- row cap and response-size cap
- value serialization that cannot leak credentials
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from datetime import date, datetime, time as dtime
from decimal import Decimal
from typing import Any
from uuid import UUID

from app.core.config import settings
from app.core.errors import ApiError
from app.services.schema_service import assert_connection_allowed, build_engine


@dataclass
class ExecutionResult:
    columns: list[dict[str, str]] = field(default_factory=list)
    rows: list[list[Any]] = field(default_factory=list)
    row_count: int = 0
    truncated: bool = False
    execution_time_ms: int = 0
    bytes: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "success": True,
            "columns": self.columns,
            "rows": self.rows,
            "metadata": {
                "row_count": self.row_count,
                "returned_rows": len(self.rows),
                "execution_time_ms": self.execution_time_ms,
                "truncated": self.truncated,
                "response_bytes": self.bytes,
            },
        }


def _serialize(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return value
    if isinstance(value, Decimal):
        f = float(value)
        # Preserve exactness when the value fits safely in a float.
        if abs(f) < 2**53:
            return f
        return str(value)
    if isinstance(value, (datetime, date, dtime)):
        return value.isoformat()
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, (bytes, bytearray, memoryview)):
        try:
            return bytes(value).decode("utf-8")
        except UnicodeDecodeError:
            return f"<binary {len(bytes(value))} bytes>"
    if isinstance(value, (dict, list, tuple)):
        try:
            json.dumps(value)
            return value
        except Exception:
            return str(value)
    return str(value)


def _type_name(type_code: Any) -> str:
    """Resolve a cursor type code to a PostgreSQL type name.

    Psycopg reports the ``pg_type`` OID (an int) in ``cursor.description``, so
    the name has to come from psycopg's type registry — reading ``.name`` off
    the code itself would silently return nothing and label every column as a
    string, which would break chart selection and client-side formatting.
    """
    if isinstance(type_code, int) and not isinstance(type_code, bool):
        try:
            from psycopg.postgres import types as pg_types

            info = pg_types.get(type_code)
            if info is not None and getattr(info, "name", None):
                return str(info.name)
        except Exception:
            pass
        return ""
    try:
        return getattr(type_code, "name", "") or str(type_code or "")
    except Exception:
        return ""


def _kind_from_name(name: str) -> str | None:
    lname = name.lower()
    if not lname:
        return None
    if "bool" in lname:
        return "boolean"
    if any(k in lname for k in ("int", "numeric", "float", "double", "real", "decimal", "money")):
        return "number"
    if any(k in lname for k in ("timestamp", "date", "time")):
        return "datetime"
    if any(k in lname for k in ("json", "xml")):
        return "json"
    if any(
        k in lname
        for k in ("char", "text", "name", "uuid", "bytea", "interval", "inet", "cidr", "macaddr", "bit")
    ):
        return "string"
    return None


def _kind_from_values(values: list[Any]) -> str | None:
    """Fallback for user-defined or unknown types: infer from the real values."""
    seen = [v for v in values if v is not None]
    if not seen:
        return None
    if all(isinstance(v, bool) for v in seen):
        return "boolean"
    if all(isinstance(v, (int, float, Decimal)) and not isinstance(v, bool) for v in seen):
        return "number"
    if all(isinstance(v, (datetime, date, dtime)) for v in seen):
        return "datetime"
    if all(isinstance(v, str) for v in seen):
        return "string"
    return None


def _column_kind(type_code: Any, values: list[Any] | None = None) -> str:
    return _kind_from_name(_type_name(type_code)) or _kind_from_values(values or []) or "string"


class QueryCancelled(Exception):
    pass


def execute_readonly(
    sql: str,
    *,
    host: str,
    port: int,
    database: str,
    username: str,
    password: str,
    ssl_mode: str = "prefer",
    max_rows: int | None = None,
    timeout_seconds: int | None = None,
) -> ExecutionResult:
    assert_connection_allowed(host)

    max_rows = max_rows or settings.max_query_rows
    timeout_seconds = timeout_seconds or settings.query_timeout_seconds

    engine = build_engine(
        host=host,
        port=port,
        database=database,
        username=username,
        password=password,
        ssl_mode=ssl_mode,
        read_only=True,
    )
    # Statement timeout enforced server-side in this session.
    started = time.perf_counter()
    try:
        with engine.connect() as conn:
            conn.exec_driver_sql(
                f"SET statement_timeout = '{int(timeout_seconds * 1000)}'"
            )
            conn.exec_driver_sql(
                "SET idle_in_transaction_session_timeout = '30000'"
            )
            cursor = conn.exec_driver_sql(sql)
            raw_columns = cursor.cursor.description or []
            rows: list[list[Any]] = []
            truncated = False
            while True:
                batch = cursor.fetchmany(500)
                if not batch:
                    break
                for r in batch:
                    if len(rows) >= max_rows:
                        truncated = True
                        break
                    rows.append([_serialize(v) for v in r])
                if truncated:
                    break
            row_count = len(rows)
            # Types are resolved after materializing rows so unknown/UDT columns
            # can still be typed from the values that actually came back.
            column_values = [
                [r[i] for r in rows if i < len(r)] for i in range(len(raw_columns))
            ]
            columns = [
                {"name": d[0], "type": _column_kind(d[1], column_values[i])}
                for i, d in enumerate(raw_columns)
            ]
    except ApiError:
        raise
    except Exception as exc:
        message = str(exc)
        lowered = message.lower()
        if "statement timeout" in lowered or "canceling statement" in lowered:
            raise ApiError(
                408,
                "query_timeout",
                f"The query exceeded the {timeout_seconds}s statement timeout and was cancelled.",
            ) from exc
        if "permission denied" in lowered or "must be owner" in lowered:
            raise ApiError(
                403,
                "query_forbidden",
                "The database role is not permitted to run this query. "
                "Use a dedicated read-only role with SELECT grants.",
            ) from exc
        if "password authentication failed" in lowered or "authentication failed" in lowered:
            raise ApiError(401, "db_auth_failed", "Database authentication failed. Check the credentials.") from exc
        if "connection" in lowered and ("refused" in lowered or "timeout" in lowered or "failed" in lowered):
            raise ApiError(
                502,
                "db_unreachable",
                f"Could not connect to the database at {host}:{port}.",
            ) from exc
        raise ApiError(500, "query_failed", _safe_db_error(message)) from exc
    finally:
        try:
            engine.dispose()
        except Exception:
            pass

    elapsed_ms = int((time.perf_counter() - started) * 1000)

    result = ExecutionResult(
        columns=columns,
        rows=rows,
        row_count=row_count,
        truncated=truncated,
        execution_time_ms=elapsed_ms,
    )
    payload = json.dumps(result.to_dict(), default=str)
    result.bytes = len(payload.encode("utf-8"))
    if result.bytes > settings.max_result_bytes:
        # Drop rows until under the response-size cap.
        while result.rows and result.bytes > settings.max_result_bytes:
            keep = max(1, int(len(result.rows) * 0.7))
            result.rows = result.rows[:keep]
            result.truncated = True
            payload = json.dumps(result.to_dict(), default=str)
            result.bytes = len(payload.encode("utf-8"))
    return result


def _safe_db_error(message: str) -> str:
    """Summarize a database error without leaking credentials or DSNs."""
    first_line = message.strip().splitlines()[0] if message.strip() else "Query failed."
    lowered = message.lower()
    if "password" in lowered or "pg_hba" in lowered:
        return "The database rejected the credentials or host policy (pg_hba.conf)."
    if "does not exist" in lowered:
        return first_line[:300]
    if "column" in lowered and "does not exist" in lowered:
        return first_line[:300]
    return first_line[:300]
