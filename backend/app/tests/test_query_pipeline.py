"""End-to-end pipeline tests: generation (fake model) -> validation -> real execution.

The real-LLM integration test lives in test_llm_integration.py and runs against
the configured Ollama server when it is available.
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from app.services.ai_service import SQLGeneration, get_ai_service, reset_ai_service
from app.tests.conftest import csrf


class FakeProvider:
    """Deterministic stand-in for the model — used ONLY in unit tests."""

    name = "fake"

    def __init__(self, response: dict):
        self.response = response

    def status(self):  # pragma: no cover
        raise NotImplementedError

    def complete(self, messages, *, json_mode=True):
        return json.dumps(self.response)


def _install_fake(monkeypatch, response: dict):
    from app.services import sql_generator

    fake = FakeProvider(response)
    monkeypatch.setattr(sql_generator, "get_ai_service", lambda: _wrap(fake))


def _wrap(provider):
    from app.services.ai_service import AIService

    svc = AIService.__new__(AIService)
    svc.provider = provider
    return svc


def _create_connection(client: TestClient, payload: dict) -> str:
    resp = client.post("/api/connections", headers=csrf(client), json=payload)
    assert resp.status_code == 201, resp.text
    return resp.json()["connection"]["id"]


def test_generate_validate_execute_with_fake_model(
    auth_client: TestClient, analytics_connection_payload: dict, monkeypatch
):
    conn_id = _create_connection(auth_client, analytics_connection_payload)

    _install_fake(
        monkeypatch,
        {
            "sql": "SELECT status, COUNT(*) AS orders FROM public.orders GROUP BY status ORDER BY 2 DESC LIMIT 100",
            "explanation": "Counts orders by status.",
            "clarification": None,
        },
    )

    gen = auth_client.post(
        "/api/query/generate",
        headers=csrf(auth_client),
        json={"connection_id": conn_id, "question": "How many orders per status?"},
    )
    assert gen.status_code == 200, gen.text
    body = gen.json()
    assert body["sql"].startswith("SELECT")
    assert body["validation"]["valid"] is True
    assert body["explanation"]

    # validate endpoint
    val = auth_client.post(
        "/api/query/validate",
        headers=csrf(auth_client),
        json={"connection_id": conn_id, "sql": body["sql"]},
    )
    assert val.json()["validation"]["valid"] is True

    # execute against the REAL analytics database
    exe = auth_client.post(
        "/api/query/execute",
        headers=csrf(auth_client),
        json={
            "connection_id": conn_id,
            "sql": body["sql"],
            "question": "How many orders per status?",
        },
    )
    assert exe.status_code == 200, exe.text
    result = exe.json()
    assert result["success"] is True
    assert isinstance(result["columns"], list) and result["columns"]
    assert result["columns"][0]["name"] == "status"
    assert len(result["rows"]) >= 1
    assert result["metadata"]["row_count"] >= 1
    assert result["metadata"]["execution_time_ms"] >= 0
    assert result["chart"] is not None
    assert result["history_id"]


def test_execute_rejects_unsafe_sql_even_if_requested(
    auth_client: TestClient, analytics_connection_payload: dict
):
    conn_id = _create_connection(auth_client, analytics_connection_payload)
    for bad in [
        "DELETE FROM orders",
        "DROP TABLE orders",
        "INSERT INTO orders (customer_id, order_date, status) VALUES (1, now(), 'x')",
        "SELECT * FROM orders; SELECT 1",
        "TRUNCATE orders",
    ]:
        resp = auth_client.post(
            "/api/query/execute",
            headers=csrf(auth_client),
            json={"connection_id": conn_id, "sql": bad, "question": "malicious"},
        )
        assert resp.status_code == 400, f"{bad} -> {resp.status_code} {resp.text}"
        assert resp.json()["error"]["code"] == "sql_rejected"


def test_execute_rejects_unknown_tables(auth_client: TestClient, analytics_connection_payload: dict):
    conn_id = _create_connection(auth_client, analytics_connection_payload)
    resp = auth_client.post(
        "/api/query/execute",
        headers=csrf(auth_client),
        json={
            "connection_id": conn_id,
            "sql": "SELECT * FROM secret_stuff",
            "question": "?",
        },
    )
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "sql_rejected"


def test_empty_result_returned_as_zero_rows(
    auth_client: TestClient, analytics_connection_payload: dict
):
    conn_id = _create_connection(auth_client, analytics_connection_payload)
    resp = auth_client.post(
        "/api/query/execute",
        headers=csrf(auth_client),
        json={
            "connection_id": conn_id,
            "sql": "SELECT * FROM orders WHERE order_date > '2100-01-01'",
            "question": "future orders",
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["rows"] == []
    assert body["metadata"]["row_count"] == 0
    assert body["chart"]["available"] is False


def test_row_limit_truncation(auth_client: TestClient, analytics_connection_payload: dict, monkeypatch):
    from app.core.config import settings

    conn_id = _create_connection(auth_client, analytics_connection_payload)
    monkeypatch.setattr(settings, "max_query_rows", 2)
    resp = auth_client.post(
        "/api/query/execute",
        headers=csrf(auth_client),
        json={"connection_id": conn_id, "sql": "SELECT order_id FROM orders ORDER BY order_id", "question": "?"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["rows"]) == 2
    assert body["metadata"]["truncated"] is True


def test_aggregation_results_are_real(
    auth_client: TestClient, analytics_connection_payload: dict
):
    """Independent cross-check: API result must equal a direct SQL execution."""
    from sqlalchemy import create_engine, text

    from app.tests.conftest import ANALYTICS

    conn_id = _create_connection(auth_client, analytics_connection_payload)
    sql = "SELECT status, COUNT(*) AS cnt FROM orders GROUP BY status ORDER BY status"
    resp = auth_client.post(
        "/api/query/execute",
        headers=csrf(auth_client),
        json={"connection_id": conn_id, "sql": sql, "question": "counts by status"},
    )
    assert resp.status_code == 200, resp.text
    api_rows = [tuple(r) for r in resp.json()["rows"]]

    url = (
        f"postgresql+psycopg://{ANALYTICS['username']}:{ANALYTICS['password']}"
        f"@{ANALYTICS['host']}:{ANALYTICS['port']}/{ANALYTICS['database']}"
    )
    engine = create_engine(url)
    with engine.connect() as c:
        direct = [tuple(r) for r in c.execute(text(sql)).all()]
    engine.dispose()

    assert api_rows == direct, f"{api_rows} != {direct}"


def test_executed_column_types_and_chart_match_the_result_shape(
    auth_client: TestClient, analytics_connection_payload: dict
):
    """Regression: psycopg reports type OIDs, so names must come from the registry.

    Before the fix every column was reported as "string", which made the chart
    recommender fall back to a plain table for numeric results.
    """
    conn_id = _create_connection(auth_client, analytics_connection_payload)
    sql = (
        "SELECT p.category, SUM(oi.quantity * oi.unit_price) AS revenue "
        "FROM order_items oi JOIN products p ON p.product_id = oi.product_id "
        "GROUP BY p.category ORDER BY revenue DESC"
    )
    resp = auth_client.post(
        "/api/query/execute",
        headers=csrf(auth_client),
        json={"connection_id": conn_id, "sql": sql, "question": "revenue by category"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()

    types = {c["name"]: c["type"] for c in body["columns"]}
    assert types["category"] == "string", types
    assert types["revenue"] == "number", types
    assert isinstance(body["rows"][0][1], (int, float))

    chart = body["chart"]
    assert chart["available"] is True, chart
    assert chart["type"] in ("bar", "pie"), chart
    assert chart["y"] == "revenue"


def test_failed_execution_is_recorded_in_history(
    auth_client: TestClient, analytics_connection_payload: dict
):
    conn_id = _create_connection(auth_client, analytics_connection_payload)
    # Valid table but bad column -> parser-level validation passes, execution fails.
    resp = auth_client.post(
        "/api/query/execute",
        headers=csrf(auth_client),
        json={"connection_id": conn_id, "sql": "SELECT nonexistent_column FROM orders", "question": "?"},
    )
    assert resp.status_code == 500
    assert resp.json()["error"]["code"] == "query_failed"

    hist = auth_client.get("/api/history")
    items = hist.json()["items"]
    assert items and items[0]["execution_status"] == "failed"
    assert items[0]["error_message"]


def test_generate_clarification_path(auth_client: TestClient, analytics_connection_payload: dict, monkeypatch):
    conn_id = _create_connection(auth_client, analytics_connection_payload)
    _install_fake(
        monkeypatch,
        {"sql": None, "explanation": "", "clarification": "Do you mean highest spending or most orders?"},
    )
    resp = auth_client.post(
        "/api/query/generate",
        headers=csrf(auth_client),
        json={"connection_id": conn_id, "question": "Show the best customers."},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["sql"] is None
    assert "spending" in body["clarification"]


def test_generate_rejects_unsafe_model_output(
    auth_client: TestClient, analytics_connection_payload: dict, monkeypatch
):
    conn_id = _create_connection(auth_client, analytics_connection_payload)
    _install_fake(monkeypatch, {"sql": "DROP TABLE orders", "explanation": "bad", "clarification": None})
    resp = auth_client.post(
        "/api/query/generate",
        headers=csrf(auth_client),
        json={"connection_id": conn_id, "question": "Remove the table"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["validation"]["valid"] is False
    assert body["success"] is False
    assert body["history_id"]

    hist = auth_client.get("/api/history").json()["items"]
    assert hist[0]["execution_status"] == "rejected"


def test_history_and_saved_query_ownership(auth_client: TestClient, client: TestClient):
    # create saved query as user A
    saved = auth_client.post(
        "/api/saved-queries",
        headers=csrf(auth_client),
        json={"title": "My query", "sql_query": "SELECT 1", "tags": ["a"], "is_favorite": True},
    )
    assert saved.status_code == 201
    item_id = saved.json()["item"]["id"]

    # patch works for owner
    patch = auth_client.patch(
        f"/api/saved-queries/{item_id}",
        headers=csrf(auth_client),
        json={"title": "Renamed", "is_favorite": False},
    )
    assert patch.status_code == 200
    assert patch.json()["item"]["title"] == "Renamed"
    assert patch.json()["item"]["tags"] == ["a"]

    # user B cannot see or modify it
    auth_client.post("/api/auth/logout", headers=csrf(auth_client))
    client.post(
        "/api/auth/register",
        headers=csrf(client),
        json={"name": "B", "email": "other@querymind.dev", "password": "Sup3rSecret!"},
    )
    assert client.get("/api/saved-queries").json()["items"] == []
    assert client.get(f"/api/saved-queries/{item_id}").status_code == 404
    assert client.patch(f"/api/saved-queries/{item_id}", headers=csrf(client), json={"title": "hacked"}).status_code == 404
    assert client.delete(f"/api/saved-queries/{item_id}", headers=csrf(client)).status_code == 404


def test_conversation_followup_uses_fresh_sql(
    auth_client: TestClient, analytics_connection_payload: dict, monkeypatch
):
    conn_id = _create_connection(auth_client, analytics_connection_payload)

    from app.services import sql_generator

    calls: list[str] = []

    class RecordingProvider(FakeProvider):
        def complete(self, messages, *, json_mode=True):
            calls.append(messages[-1]["content"])
            n = len(calls)
            return json.dumps(
                {
                    "sql": f"SELECT order_id FROM orders LIMIT {5 * n}",
                    "explanation": f"attempt {n}",
                    "clarification": None,
                }
            )

    monkeypatch.setattr(sql_generator, "get_ai_service", lambda: _wrap(RecordingProvider({})))

    conv = auth_client.post(
        "/api/conversations",
        headers=csrf(auth_client),
        json={"connection_id": conn_id, "title": "Test"},
    )
    conv_id = conv.json()["conversation"]["id"]

    first = auth_client.post(
        f"/api/conversations/{conv_id}/messages",
        headers=csrf(auth_client),
        json={"question": "Show orders", "connection_id": conn_id},
    )
    assert first.status_code == 200, first.text
    assert first.json()["sql"].endswith("LIMIT 5")

    second = auth_client.post(
        f"/api/conversations/{conv_id}/messages",
        headers=csrf(auth_client),
        json={"question": "Only the recent ones", "connection_id": conn_id},
    )
    assert second.status_code == 200
    # second turn generated DIFFERENT sql and included prior context
    assert second.json()["sql"].endswith("LIMIT 10")
    assert "Show orders" in calls[1]

    detail = auth_client.get(f"/api/conversations/{conv_id}")
    roles = [m["role"] for m in detail.json()["messages"]]
    assert roles == ["user", "assistant", "user", "assistant"]


def test_overview_stats_come_from_data(
    auth_client: TestClient, analytics_connection_payload: dict
):
    empty = auth_client.get("/api/analytics/overview").json()["stats"]
    assert empty["connections"] == 0 and empty["total_queries"] == 0

    _create_connection(auth_client, analytics_connection_payload)
    conn_id = auth_client.get("/api/connections").json()["items"][0]["id"]
    auth_client.post(
        "/api/query/execute",
        headers=csrf(auth_client),
        json={"connection_id": conn_id, "sql": "SELECT 1 AS one", "question": "one"},
    )
    stats = auth_client.get("/api/analytics/overview").json()["stats"]
    assert stats["connections"] == 1
    assert stats["total_queries"] == 1
    assert stats["successful_queries"] == 1
