"""CSV upload: parse, validate, infer types, and materialize an analytical dataset.

Datasets are created in the user's *selected analytical database* under a
dedicated `querymind_uploads` schema so they never mix with protected
application metadata tables. Inserts are parameterized; file contents are never
executed as SQL.
"""

from __future__ import annotations

import io
import json
import re
import unicodedata
from typing import Any

import pandas as pd
from sqlalchemy import text

from app.core.errors import ApiError

MAX_UPLOAD_BYTES = 5 * 1024 * 1024  # 5 MB
MAX_ROWS = 50_000
UPLOAD_SCHEMA = "querymind_uploads"

_SAFE_IDENT = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")


def sanitize_identifier(raw: str, *, fallback: str = "col") -> str:
    """Turn arbitrary text into a safe lowercase SQL identifier (<=63 chars)."""
    text_val = unicodedata.normalize("NFKD", raw or "")
    text_val = text_val.encode("ascii", "ignore").decode("ascii")
    text_val = re.sub(r"[^a-zA-Z0-9_]+", "_", text_val).strip("_").lower()
    if not text_val:
        text_val = fallback
    if text_val[0].isdigit():
        text_val = f"{fallback}_{text_val}"
    return text_val[:63]


def parse_csv(content: bytes, filename: str) -> tuple[pd.DataFrame, list[dict[str, str]]]:
    if len(content) > MAX_UPLOAD_BYTES:
        raise ApiError(
            413,
            "file_too_large",
            f"CSV files are limited to {MAX_UPLOAD_BYTES // (1024 * 1024)} MB.",
        )
    if not content:
        raise ApiError(400, "empty_file", "The uploaded file is empty.")
    if b"\x00" in content:
        raise ApiError(
            400,
            "invalid_csv",
            "The file contains binary data (null bytes). Upload a plain-text CSV file.",
        )

    for encoding in ("utf-8-sig", "utf-8", "latin-1"):
        try:
            text_content = content.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    else:
        raise ApiError(
            400,
            "invalid_encoding",
            "The file could not be decoded. Upload a UTF-8 CSV file.",
        )

    try:
        df = pd.read_csv(io.StringIO(text_content))
    except Exception as exc:
        raise ApiError(400, "invalid_csv", f"Could not parse the CSV file: {exc}") from exc

    if df.empty and len(df.columns) == 0:
        raise ApiError(400, "invalid_csv", "The CSV file has no columns.")
    if len(df) > MAX_ROWS:
        raise ApiError(413, "too_many_rows", f"CSV uploads are limited to {MAX_ROWS} rows.")

    df.columns = [sanitize_identifier(str(c), fallback=f"column_{i+1}") for i, c in enumerate(df.columns)]
    # Disambiguate duplicate column names after sanitization.
    seen: dict[str, int] = {}
    unique_cols: list[str] = []
    for c in df.columns:
        if c in seen:
            seen[c] += 1
            c = f"{c}_{seen[c]}"
        else:
            seen[c] = 1
        unique_cols.append(c)
    df.columns = unique_cols

    columns: list[dict[str, str]] = []
    for c in df.columns:
        dtype = df[c].dtype
        if pd.api.types.is_bool_dtype(dtype):
            pg = "boolean"
        elif pd.api.types.is_integer_dtype(dtype):
            pg = "bigint"
        elif pd.api.types.is_float_dtype(dtype):
            pg = "double precision"
        else:
            pg = "text"
        columns.append({"name": c, "type": pg, "pandas": str(dtype)})
    return df, columns


def _pg_literal(value: Any, pg_type: str) -> Any:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    if pd.isna(value):
        return None
    if pg_type in {"bigint", "double precision", "boolean"}:
        if pg_type == "boolean":
            return bool(value)
        if pg_type == "bigint":
            return int(value)
        return float(value)
    return str(value)


def create_dataset(
    engine,
    *,
    df: pd.DataFrame,
    columns: list[dict[str, str]],
    table_name: str,
    persistent: bool,
    user_id: str,
) -> dict[str, Any]:
    table = sanitize_identifier(table_name, fallback="dataset")
    with engine.begin() as conn:
        conn.exec_driver_sql(f'CREATE SCHEMA IF NOT EXISTS "{UPLOAD_SCHEMA}"')
        conn.exec_driver_sql(f'DROP TABLE IF EXISTS "{UPLOAD_SCHEMA}"."{table}"')
        col_ddl = ", ".join(f'"{c["name"]}" {c["type"]}' for c in columns)
        conn.exec_driver_sql(f'CREATE TABLE "{UPLOAD_SCHEMA}"."{table}" ({col_ddl})')

        placeholders = ", ".join([f":p{i}" for i in range(len(columns))])
        insert_sql = (
            f'INSERT INTO "{UPLOAD_SCHEMA}"."{table}" '
            f'({", ".join(chr(34) + c["name"] + chr(34) for c in columns)}) '
            f"VALUES ({placeholders})"
        )
        stmt = text(insert_sql)
        records = []
        for _, row in df.iterrows():
            records.append(
                {f"p{i}": _pg_literal(row[c["name"]], c["type"]) for i, c in enumerate(columns)}
            )
        if records:
            conn.execute(stmt, records)

    return {
        "table": table,
        "schema": UPLOAD_SCHEMA,
        "qualified_name": f"{UPLOAD_SCHEMA}.{table}",
        "persistent": persistent,
        "row_count": len(df),
        "columns": columns,
        "metadata": {"user_id": user_id, "filename_columns": len(columns)},
    }


def drop_dataset(engine, table_name: str) -> None:
    table = sanitize_identifier(table_name, fallback="dataset")
    with engine.begin() as conn:
        conn.exec_driver_sql(f'DROP TABLE IF EXISTS "{UPLOAD_SCHEMA}"."{table}"')


def columns_preview(columns: list[dict[str, str]]) -> str:
    return json.dumps(columns, indent=2)
