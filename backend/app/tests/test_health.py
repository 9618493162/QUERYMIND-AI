"""Health contracts: liveness, readiness and cached provider diagnostics."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.api import health as health_module


def test_liveness_does_not_touch_the_database(client: TestClient, monkeypatch):
    """A database outage must not make a healthy process look dead."""

    def explode(*_args, **_kwargs):
        raise AssertionError("liveness must not query the database")

    monkeypatch.setattr(health_module, "get_engine", explode)

    resp = client.get("/api/health")

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["probe"] == "liveness"
    assert "database" not in body


def test_readiness_reports_connected_database(client: TestClient):
    """Real PostgreSQL round trip: readiness succeeds when the DB answers."""
    resp = client.get("/api/health/ready")

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["probe"] == "readiness"
    assert body["database"]["connected"] is True


def test_readiness_returns_503_when_database_is_unreachable(
    client: TestClient, monkeypatch
):
    class BoomEngine:
        def connect(self):
            raise RuntimeError("database is down")

    monkeypatch.setattr(health_module, "get_engine", lambda: BoomEngine())

    resp = client.get("/api/health/ready")

    assert resp.status_code == 503
    body = resp.json()
    assert body["status"] == "unavailable"
    assert body["database"]["connected"] is False


def test_ai_status_is_cached_between_probes(client: TestClient, monkeypatch):
    """Repeated health probes must not hammer the model server."""
    calls = {"n": 0}

    class FakeProvider:
        def status(self):
            calls["n"] += 1
            return health_module.AIStatus(
                available=True,
                provider="ollama",
                model="test-model",
                message="reachable",
                models=["test-model"],
                latency_ms=1,
            )

    monkeypatch.setattr(health_module, "build_provider", lambda: FakeProvider())
    monkeypatch.setattr(health_module.settings, "ai_health_cache_seconds", 30.0)
    health_module.reset_ai_status_cache()

    first = client.get("/api/health/ai")
    second = client.get("/api/health/ai")

    assert calls["n"] == 1, "the provider must be probed once per cache window"
    assert first.json()["status"] == "ok"
    assert second.json()["status"] == "ok"
    assert second.json()["model"] == "test-model"


def test_ai_status_cache_can_be_disabled(client: TestClient, monkeypatch):
    calls = {"n": 0}

    class FakeProvider:
        def status(self):
            calls["n"] += 1
            return health_module.AIStatus(
                available=False, provider="ollama", model="m", message="down"
            )

    monkeypatch.setattr(health_module, "build_provider", lambda: FakeProvider())
    monkeypatch.setattr(health_module.settings, "ai_health_cache_seconds", 0.0)
    health_module.reset_ai_status_cache()

    assert client.get("/api/health/ai").json()["status"] == "unavailable"
    assert client.get("/api/health/ai").json()["status"] == "unavailable"
    assert calls["n"] == 2, "a zero TTL must probe every time"


def test_ai_health_matches_the_real_provider(client: TestClient):
    """Against the configured provider (Ollama): the report is real, never faked.

    Status may be ok or unavailable depending on whether the model server is
    reachable in this environment; either way the payload must describe the real
    provider and model rather than a placeholder.
    """
    from app.core.config import settings

    body = client.get("/api/health/ai").json()

    assert body["provider"] == settings.ai_provider
    assert body["model"] == settings.ollama_model
    assert body["status"] in {"ok", "unavailable"}
    assert isinstance(body["models"], list)
    if body["status"] == "unavailable":
        assert body["message"], "an unavailable provider must explain why"
