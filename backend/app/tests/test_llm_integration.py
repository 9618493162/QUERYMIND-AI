"""Real LLM integration test.

Runs against the configured Ollama server. Skips (with a clear reason) when the
provider or model is unavailable — it never fakes a model response.

Set ``REQUIRE_LIVE_LLM=1`` (the CI live job does) to turn that skip into a
failure, so an unreachable model can never be reported as a passing test run.
"""

from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

from app.services.ai_service import build_provider
from app.tests.conftest import csrf

pytestmark = pytest.mark.live_llm


def _ai_status():
    return build_provider().status()


def _require_provider(status) -> None:
    """Skip locally without a model; fail loudly when the run demands a model."""
    if status.available:
        return
    message = f"AI provider unavailable: {status.message}"
    if os.environ.get("REQUIRE_LIVE_LLM") == "1":
        pytest.fail(f"{message} (REQUIRE_LIVE_LLM=1 forbids skipping the real model)")
    pytest.skip(message)


def _create_connection(client: TestClient, payload: dict) -> str:
    resp = client.post("/api/connections", headers=csrf(client), json=payload)
    assert resp.status_code == 201, resp.text
    return resp.json()["connection"]["id"]


def test_ai_provider_reports_real_status():
    status = _ai_status()
    assert status.provider == "ollama"
    # The endpoint must report truthfully either way.
    assert isinstance(status.available, bool)
    assert status.message


def test_real_llm_generates_valid_sql(auth_client: TestClient, analytics_connection_payload: dict):
    _require_provider(_ai_status())

    conn_id = _create_connection(auth_client, analytics_connection_payload)
    resp = auth_client.post(
        "/api/query/generate",
        headers=csrf(auth_client),
        json={"connection_id": conn_id, "question": "How many orders are there for each status?"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["sql"], f"model produced no SQL: {body}"
    assert body["validation"]["valid"], f"generated SQL failed validation: {body['validation']['errors']}"
    assert "orders" in body["sql"].lower()

    # Execute the model-generated SQL against the real database.
    exe = auth_client.post(
        "/api/query/execute",
        headers=csrf(auth_client),
        json={
            "connection_id": conn_id,
            "sql": body["sql"],
            "question": "How many orders are there for each status?",
        },
    )
    assert exe.status_code == 200, exe.text
    result = exe.json()
    assert result["rows"], "expected real rows from the analytics database"


def test_real_llm_handles_clarification(auth_client: TestClient, analytics_connection_payload: dict):
    _require_provider(_ai_status())

    conn_id = _create_connection(auth_client, analytics_connection_payload)
    resp = auth_client.post(
        "/api/query/generate",
        headers=csrf(auth_client),
        json={"connection_id": conn_id, "question": "Show the best customers."},
    )
    assert resp.status_code == 200
    body = resp.json()
    # Either it clarifies the ambiguity, or it produces valid SQL — never junk.
    assert (body["sql"] and body["validation"]["valid"]) or body["clarification"]
