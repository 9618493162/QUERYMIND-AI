"""Unit tests for the NVIDIA NIM provider.

All HTTP goes through ``httpx.MockTransport``: no network access, and no
fabricated AI responses in production code paths — the provider must either
return the (mocked) provider output or raise ``AIProviderError``.

Covered per requirement: success, authentication failure, timeout, malformed
response, and provider selection.
"""

from __future__ import annotations

import httpx
import pytest

from app.core.config import settings
from app.core.errors import ApiError
from app.services.ai_service import (
    AIProviderError,
    NVIDIAProvider,
    OllamaProvider,
    build_provider,
)

API_KEY = "nvapi-unit-test-key-do-not-leak"
# Deliberately a *configured* ID, never an assumed/hardcoded one.
MODEL = "acme/custom-sql-model-1"
BASE_URL = "https://integrate.api.nvidia.com/v1"

MESSAGES = [
    {"role": "system", "content": "You are QueryMind."},
    {"role": "user", "content": "How many orders?"},
]


def make_provider(
    handler,
    *,
    retries: int = 0,
    model: str = MODEL,
    api_key: str = API_KEY,
    base_url: str = BASE_URL,
    timeout: float = 5.0,
) -> NVIDIAProvider:
    return NVIDIAProvider(
        base_url=base_url,
        api_key=api_key,
        model=model,
        timeout=timeout,
        max_retries=retries,
        transport=httpx.MockTransport(handler),
    )


def json_response(request: httpx.Request, status: int, body) -> httpx.Response:
    import json as _json

    return httpx.Response(
        status, content=_json.dumps(body), headers={"content-type": "application/json"}, request=request
    )


# --- success ----------------------------------------------------------------


def test_complete_success_posts_chat_completions():
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["method"] = request.method
        seen["url"] = str(request.url)
        seen["authorization"] = request.headers.get("authorization")
        body = request.content.decode()
        seen["payload"] = body
        return json_response(
            request,
            200,
            {
                "choices": [
                    {"message": {"role": "assistant", "content": '{"sql": "SELECT 1"}'}}
                ]
            },
        )

    provider = make_provider(handler)
    content = provider.complete(MESSAGES, json_mode=True)

    assert content == '{"sql": "SELECT 1"}'
    assert seen["method"] == "POST"
    assert seen["url"] == f"{BASE_URL}/chat/completions"
    assert seen["authorization"] == f"Bearer {API_KEY}"

    import json as _json

    payload = _json.loads(seen["payload"])
    assert payload["model"] == MODEL, "the configured NVIDIA_MODEL must be used verbatim"
    assert payload["messages"] == MESSAGES, "the existing messages format must pass through"
    assert payload["temperature"] == 0, "temperature must stay at 0"
    assert payload["stream"] is False
    assert payload["response_format"] == {"type": "json_object"}


def test_complete_without_json_mode_omits_response_format():
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        import json as _json

        captured.update(_json.loads(request.content))
        return json_response(
            request, 200, {"choices": [{"message": {"content": "plain text"}}]}
        )

    provider = make_provider(handler)
    assert provider.complete(MESSAGES, json_mode=False) == "plain text"
    assert "response_format" not in captured
    assert captured["temperature"] == 0


def test_complete_retries_once_without_response_format_when_unsupported():
    """Endpoints that reject response_format must not break JSON generation."""
    attempts: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        import json as _json

        payload = _json.loads(request.content)
        attempts.append(payload)
        if "response_format" in payload:
            return json_response(
                request,
                400,
                {"error": {"message": "response_format json_object is not supported"}},
            )
        return json_response(
            request, 200, {"choices": [{"message": {"content": '{"sql": "SELECT 2"}'}}]}
        )

    provider = make_provider(handler, retries=2)
    assert provider.complete(MESSAGES, json_mode=True) == '{"sql": "SELECT 2"}'
    assert len(attempts) == 2
    assert "response_format" in attempts[0]
    assert "response_format" not in attempts[1]


def test_status_success_reports_available_model():
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["authorization"] = request.headers.get("authorization")
        return json_response(request, 200, {"data": [{"id": MODEL}, {"id": "other/model"}]})

    status = make_provider(handler).status()

    assert seen["url"] == f"{BASE_URL}/models"
    assert seen["authorization"] == f"Bearer {API_KEY}", "the probe must authenticate"
    assert status.available is True
    assert status.provider == "nvidia"
    assert status.model == MODEL
    assert MODEL in status.models
    assert status.latency_ms is not None


def test_status_model_not_listed_is_reported_honestly():
    def handler(request: httpx.Request) -> httpx.Response:
        return json_response(request, 200, {"data": [{"id": "someone/else"}]})

    status = make_provider(handler).status()

    assert status.available is False
    assert MODEL in status.message
    assert "someone/else" in status.message


def test_base_url_is_configurable():
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        return json_response(
            request, 200, {"choices": [{"message": {"content": "ok"}}]}
        )

    provider = make_provider(handler, base_url="https://gateway.example.com/nim/v3")
    assert provider.complete(MESSAGES) == "ok"
    assert seen["url"] == "https://gateway.example.com/nim/v3/chat/completions"


# --- authentication failure -------------------------------------------------


def test_complete_auth_failure_raises_and_never_leaks_the_key():
    def handler(request: httpx.Request) -> httpx.Response:
        return json_response(
            request,
            401,
            {"error": {"message": f"Invalid API key: {API_KEY}"}},
        )

    provider = make_provider(handler)
    with pytest.raises(AIProviderError) as exc:
        provider.complete(MESSAGES)

    assert exc.value.code == "provider_error"
    assert "NVIDIA_API_KEY" in exc.value.message
    assert API_KEY not in exc.value.message, "the API key must never appear in errors"


def test_status_auth_failure_never_leaks_the_key():
    def handler(request: httpx.Request) -> httpx.Response:
        return json_response(
            request, 401, {"error": {"message": f"unauthorized for {API_KEY}"}}
        )

    status = make_provider(handler).status()

    assert status.available is False
    assert "NVIDIA_API_KEY" in status.message
    assert API_KEY not in status.message, "the API key must never appear in status output"


def test_missing_api_key_is_reported_not_faked():
    provider = make_provider(lambda request: httpx.Response(500, request=request), api_key="")

    status = provider.status()
    assert status.available is False
    assert "NVIDIA_API_KEY" in status.message

    with pytest.raises(AIProviderError) as exc:
        provider.complete(MESSAGES)
    assert API_KEY not in exc.value.message


def test_missing_model_is_reported_not_faked():
    provider = make_provider(
        lambda request: json_response(request, 200, {"data": []}), model=""
    )

    status = provider.status()
    assert status.available is False
    assert "NVIDIA_MODEL" in status.message

    with pytest.raises(AIProviderError) as exc:
        provider.complete(MESSAGES)
    assert exc.value.code == "model_missing"


# --- timeout ----------------------------------------------------------------


def test_complete_timeout_raises_provider_unavailable():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timed out", request=request)

    provider = make_provider(handler, timeout=5.0, retries=1)
    with pytest.raises(AIProviderError) as exc:
        provider.complete(MESSAGES)

    assert exc.value.code == "provider_unavailable"
    assert "5s" in exc.value.message, "the timeout must be explained to the user"


def test_status_timeout_reports_unavailable():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("timed out", request=request)

    status = make_provider(handler, timeout=5.0).status()

    assert status.available is False
    assert "did not answer" in status.message
    assert API_KEY not in status.message


# --- malformed response -----------------------------------------------------


def test_complete_invalid_json_body_raises_provider_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content="<html>not json</html>", request=request)

    provider = make_provider(handler, retries=1)
    with pytest.raises(AIProviderError) as exc:
        provider.complete(MESSAGES)

    assert exc.value.code == "provider_unavailable"
    assert "malformed" in exc.value.message


def test_complete_missing_choices_raises_provider_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return json_response(request, 200, {"id": "resp-1", "choices": []})

    provider = make_provider(handler, retries=0)
    with pytest.raises(AIProviderError) as exc:
        provider.complete(MESSAGES)

    assert exc.value.code == "provider_unavailable"
    assert "empty response" in exc.value.message


def test_complete_server_error_is_retried_then_reported():
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(503, text="capacity", request=request)

    provider = make_provider(handler, retries=2)
    with pytest.raises(AIProviderError) as exc:
        provider.complete(MESSAGES)

    assert calls["n"] == 3, "5xx must be retried max_retries+1 times"
    assert exc.value.code == "provider_unavailable"
    assert "503" in exc.value.message


# --- provider selection -----------------------------------------------------


def test_build_provider_selects_nvidia_from_settings(monkeypatch):
    monkeypatch.setattr(settings, "ai_provider", "nvidia")
    monkeypatch.setattr(settings, "nvidia_api_key", API_KEY)
    monkeypatch.setattr(settings, "nvidia_base_url", "https://nim.example.com/v1")
    monkeypatch.setattr(settings, "nvidia_model", MODEL)
    monkeypatch.setattr(settings, "ai_timeout_seconds", 42.0)
    monkeypatch.setattr(settings, "ai_max_retries", 3)

    provider = build_provider()

    assert isinstance(provider, NVIDIAProvider)
    assert provider.name == "nvidia"
    assert provider.api_key == API_KEY
    assert provider.base_url == "https://nim.example.com/v1"
    assert provider.model == MODEL
    assert provider.timeout == 42.0
    assert provider.max_retries == 3


def test_build_provider_defaults_to_ollama(monkeypatch):
    monkeypatch.setattr(settings, "ai_provider", "ollama")

    provider = build_provider()

    assert isinstance(provider, OllamaProvider)
    assert provider.name == "ollama"


def test_build_provider_rejects_unknown_provider(monkeypatch):
    monkeypatch.setattr(settings, "ai_provider", "some-future-provider")

    with pytest.raises(ApiError) as exc:
        build_provider()

    assert exc.value.status_code == 503
    assert "ollama" in exc.value.message and "nvidia" in exc.value.message


def test_nvidia_defaults_match_the_documented_contract():
    """NVIDIA_BASE_URL defaults to NVIDIA's documented endpoint; model is not assumed."""
    fresh = settings.__class__()
    assert fresh.nvidia_base_url == "https://integrate.api.nvidia.com/v1"
    assert fresh.nvidia_model == ""
    assert fresh.nvidia_api_key == ""
    assert fresh.ai_provider == "ollama"


def test_validate_for_runtime_requires_nvidia_configuration(monkeypatch):
    monkeypatch.setattr(settings, "ai_provider", "nvidia")
    monkeypatch.setattr(settings, "nvidia_api_key", "")
    monkeypatch.setattr(settings, "nvidia_model", "")

    problems = settings.validate_for_runtime()

    assert any("NVIDIA_API_KEY" in p for p in problems)
    assert any("NVIDIA_MODEL" in p for p in problems)

    # Complete configuration removes the NVIDIA-specific problems.
    monkeypatch.setattr(settings, "nvidia_api_key", API_KEY)
    monkeypatch.setattr(settings, "nvidia_model", MODEL)
    remaining = [
        p for p in settings.validate_for_runtime() if p.startswith("NVIDIA_")
    ]
    assert remaining == []
