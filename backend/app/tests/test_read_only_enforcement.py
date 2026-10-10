"""Read-only enforcement with a real, restricted PostgreSQL role.

Defence in depth means the database itself refuses writes, not just the
application's SQL validator. CI provisions a SELECT-only role
(`analytics_ro`) and exports the `QM_READONLY_*` variables; without them the
tests skip with an explicit reason (reported as skipped, never as passed).

Covered here:
  * the restricted role can run SELECT through the application;
  * the role cannot INSERT/UPDATE/DELETE/DROP even with direct SQL;
  * the application's read-only session rejects writes server-side.
"""

from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

from app.tests.conftest import ANALYTICS, csrf

pytestmark = pytest.mark.reads_only

READONLY = {
    "host": os.environ.get("QM_READONLY_HOST") or ANALYTICS["host"],
    "port": int(os.environ.get("QM_READONLY_PORT") or ANALYTICS["port"]),
    "database": os.environ.get("QM_READONLY_DB") or ANALYTICS["database"],
    "username": os.environ.get("QM_READONLY_USER", ""),
    "password": os.environ.get("QM_READONLY_PASSWORD", ""),
}


def _require_role() -> None:
    if not READONLY["username"] or not READONLY["password"]:
        pytest.skip(
            "read-only role not configured (set QM_READONLY_USER/QM_READONLY_PASSWORD; "
            "CI creates an 'analytics_ro' role with SELECT-only grants)"
        )


def _payload(name: str) -> dict:
    return {
        "name": name,
        "database_type": "postgresql",
        "host": READONLY["host"],
        "port": READONLY["port"],
        "database_name": READONLY["database"],
        "username": READONLY["username"],
        "password": READONLY["password"],
        "ssl_mode": "disable",
    }


def _psycopg():
    psycopg = pytest.importorskip("psycopg")
    return psycopg


def test_readonly_role_can_select_through_the_application(
    auth_client: TestClient, monkeypatch
):
    _require_role()
    payload = _payload("Read-only analytics role")
    created = auth_client.post("/api/connections", headers=csrf(auth_client), json=payload)
    assert created.status_code == 201, created.text
    conn_id = created.json()["connection"]["id"]

    resp = auth_client.post(
        "/api/query/execute",
        headers=csrf(auth_client),
        json={
            "connection_id": conn_id,
            "sql": "SELECT region_name FROM regions ORDER BY region_name",
            "question": "list regions",
        },
    )
    assert resp.status_code == 200, resp.text
    names = [row[0] for row in resp.json()["rows"]]
    assert names, "expected the sample regions to be readable by the SELECT-only role"


def test_readonly_role_cannot_write_or_drop():
    _require_role()
    psycopg = _psycopg()
    with psycopg.connect(
        host=READONLY["host"],
        port=READONLY["port"],
        dbname=READONLY["database"],
        user=READONLY["username"],
        password=READONLY["password"],
        connect_timeout=10,
    ) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM orders")
            assert cur.fetchone()[0] > 0

            for statement in (
                "INSERT INTO orders (customer_id, order_date, status) VALUES (1, '2025-01-01', 'x')",
                "UPDATE orders SET status = 'x'",
                "DELETE FROM orders",
                "DROP TABLE orders",
                "CREATE TABLE ci_should_not_exist (id int)",
            ):
                with pytest.raises(psycopg.Error) as excinfo:
                    cur.execute(statement)
                conn.rollback()
                message = str(excinfo.value).lower()
                assert (
                    "permission denied" in message
                    or "read-only" in message
                    or "must be owner" in message
                ), f"{statement} was not refused by the database: {excinfo.value}"


def test_application_readonly_session_refuses_writes_server_side():
    """Even if a write reached the driver, the session is read-only."""
    _require_role()
    from sqlalchemy import text
    from sqlalchemy.exc import DBAPIError

    from app.services.schema_service import build_engine

    engine = build_engine(
        host=READONLY["host"],
        port=READONLY["port"],
        database=READONLY["database"],
        username=READONLY["username"],
        password=READONLY["password"],
        ssl_mode="disable",
        read_only=True,
    )
    try:
        with engine.connect() as conn:
            assert conn.execute(text("SELECT 1")).scalar_one() == 1
            # PostgreSQL raises SQLSTATE 25006 (read_only_sql_transaction),
            # which SQLAlchemy surfaces as InternalError/DBAPIError.
            with pytest.raises(DBAPIError) as excinfo:
                conn.exec_driver_sql("CREATE TEMP TABLE ci_write_probe (id int)")
            assert "read-only" in str(excinfo.value).lower()
    finally:
        engine.dispose()
