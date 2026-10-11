"""Runtime safety: database pooling, trusted proxies and log redaction.

These are the deployment-facing controls: how many connections a process may
open, whose ``X-Forwarded-For`` header may be believed, and what may appear in
a server log when something goes wrong.
"""

from __future__ import annotations

import asyncio
import json
import logging

import pytest
from pydantic import ValidationError
from starlette.requests import Request

from app.api import uploads as uploads_module
from app.core import rate_limit
from app.core.config import Settings, settings as global_settings
from app.core.errors import redact, unhandled_error_handler
from app.services import csv_service


def _production_settings(**overrides) -> Settings:
    base = dict(
        app_env="production",
        app_secret_key="prod-secret-key-abc123notforrealdeploy",
        encryption_key="test-encryption-key-0123456789abcdef",
        frontend_origin="https://app.example.com",
        database_url=(
            "postgresql+psycopg://app_user:pw@db.example.com:5432/querymind?sslmode=require"
        ),
    )
    base.update(overrides)
    return Settings(**base)


# --- database pool configuration -------------------------------------------

def test_database_pool_is_configurable_and_bounded():
    configured = Settings(db_pool_size=3, db_max_overflow=2)
    assert configured.max_db_connections == 5

    # A pool of zero would make every request wait forever.
    with pytest.raises(ValidationError):
        Settings(db_pool_size=0)
    with pytest.raises(ValidationError):
        Settings(db_max_overflow=-1)


def test_production_requires_tls_for_a_remote_metadata_database():
    insecure = _production_settings(
        database_url="postgresql+psycopg://app_user:pw@db.example.com:5432/querymind"
    )
    assert any("TLS" in p for p in insecure.validate_production_security())

    # An explicit, documented opt-out is allowed (private network only).
    opted_out = _production_settings(
        database_url="postgresql+psycopg://app_user:pw@postgres:5432/querymind",
        require_db_tls=False,
    )
    assert opted_out.validate_production_security() == []


def test_local_database_does_not_require_tls():
    local = _production_settings(
        database_url="postgresql+psycopg://app_user:pw@localhost:5432/querymind"
    )
    assert local.validate_production_security() == []


def test_log_level_is_validated():
    assert Settings(log_level="debug").log_level == "DEBUG"
    with pytest.raises(ValidationError):
        Settings(log_level="chatty")


# --- trusted proxy handling -----------------------------------------------

def _request(peer: str, xff: str | None = None) -> Request:
    headers = []
    if xff is not None:
        headers.append((b"x-forwarded-for", xff.encode()))
    scope = {
        "type": "http",
        "http_version": "1.1",
        "method": "GET",
        "scheme": "https",
        "path": "/api/query/generate",
        "raw_path": b"/api/query/generate",
        "query_string": b"",
        "headers": headers,
        "client": (peer, 45678),
        "server": ("app.example.com", 443),
    }
    return Request(scope)


def test_forwarded_header_is_ignored_when_no_proxy_is_trusted(monkeypatch):
    monkeypatch.setattr(global_settings, "trusted_proxy_ips", "")
    request = _request("172.28.0.5", "203.0.113.9")
    assert rate_limit.client_key(request) == "172.28.0.5"


def test_forwarded_header_is_ignored_from_an_untrusted_peer(monkeypatch):
    monkeypatch.setattr(global_settings, "trusted_proxy_ips", "172.28.0.0/24")
    # The peer is a random host, not the configured proxy: its header is a lie.
    request = _request("198.51.100.4", "203.0.113.9")
    assert rate_limit.client_key(request) == "198.51.100.4"


def test_trusted_proxy_chain_uses_the_real_client(monkeypatch):
    monkeypatch.setattr(global_settings, "trusted_proxy_ips", "172.28.0.0/24")
    request = _request("172.28.0.5", "203.0.113.9")
    assert rate_limit.client_key(request) == "203.0.113.9"


def test_spoofed_leftmost_entry_cannot_win(monkeypatch):
    """A client that prepends a fake IP must not be able to rotate its bucket."""
    monkeypatch.setattr(global_settings, "trusted_proxy_ips", "172.28.0.0/24")
    request = _request("172.28.0.5", "9.9.9.9, 203.0.113.9")
    assert rate_limit.client_key(request) == "203.0.113.9"


def test_trusted_hops_and_garbage_are_skipped(monkeypatch):
    monkeypatch.setattr(global_settings, "trusted_proxy_ips", "172.28.0.0/24")
    request = _request("172.28.0.5", "not-an-ip, 172.28.0.9, 203.0.113.9")
    assert rate_limit.client_key(request) == "203.0.113.9"


def test_trusted_proxies_are_parsed_from_config():
    configured = Settings(trusted_proxy_ips="172.28.0.0/24, 10.1.2.3")
    assert configured.trusted_proxies == ["172.28.0.0/24", "10.1.2.3"]
    assert Settings(trusted_proxy_ips="").trusted_proxies == []


# --- log redaction ---------------------------------------------------------

def test_redact_masks_credentials_tokens_and_sql_parameters():
    raw = (
        "connection failed: postgresql+psycopg://app_user:s3cret@db:5432/querymind "
        "password=hunter2 token=abc123 "
        "[parameters: ('alice', 'hunter2')] "
        "X-CSRF-Token: deadbeefcafe"
    )

    out = redact(raw)

    for secret in ("s3cret", "hunter2", "abc123", "deadbeefcafe"):
        assert secret not in out, f"{secret!r} must not appear in logs"
    assert "app_user" in out  # the username is not a credential we must hide
    assert "[parameters: ***]" in out


def test_redact_truncates_very_long_output():
    out = redact("x" * 20_000)
    assert len(out) < 20_000
    assert out.endswith("...(truncated)")


def test_unhandled_exception_is_logged_redacted_and_not_leaked(caplog):
    caplog.set_level(logging.ERROR, logger="querymind.errors")

    request = _request("172.28.0.5")
    request.state.request_id = "req-1234"
    exc = RuntimeError("boom password=hunter2 [parameters: ('secret-value',)]")

    resp = asyncio.run(unhandled_error_handler(request, exc))

    # The client gets a generic message...
    assert resp.status_code == 500
    body = json.loads(resp.body)
    assert body["error"]["code"] == "internal_error"
    assert "hunter2" not in json.dumps(body)
    assert "secret-value" not in json.dumps(body)

    # ...while the server log has a structured, redacted, correlated record.
    records = [r.getMessage() for r in caplog.records if "unhandled_exception" in r.getMessage()]
    assert records, "the exception must be logged server-side"
    payload = json.loads(records[0])
    assert payload["event"] == "unhandled_exception"
    assert payload["request_id"] == "req-1234"
    assert payload["error_type"] == "RuntimeError"
    assert payload["path"] == "/api/query/generate"
    assert "hunter2" not in records[0]
    assert "secret-value" not in records[0]


def test_redaction_covers_traceback_text():
    """Driver exceptions embed bound parameters in their message/traceback."""
    formatted = (
        'Traceback (most recent call last):\n'
        '  File "x.py", line 1, in <module>\n'
        "psycopg.errors.UndefinedTable: relation does not exist\n"
        "[SQL: SELECT * FROM t WHERE pw = %(pw)s]\n"
        "[parameters: {'pw': 'hunter2'}]\n"
        "postgresql://user:hunter2@host/db\n"
    )

    out = redact(formatted)

    assert "hunter2" not in out
    assert "[parameters: ***]" in out
    assert "SELECT * FROM t" in out  # SQL text stays for diagnosis


# --- streaming upload limit ------------------------------------------------

class _FakeUpload:
    """Minimal UploadFile stand-in that records how much was actually read."""

    def __init__(self, total: int, chunk: int = 64 * 1024) -> None:
        self.remaining = total
        self.chunk = chunk
        self.bytes_read = 0

    async def read(self, size: int = -1) -> bytes:
        if self.remaining <= 0:
            return b""
        n = min(size if size and size > 0 else self.chunk, self.remaining)
        self.remaining -= n
        self.bytes_read += n
        return b"x" * n


def test_streaming_upload_limit_aborts_before_buffering_everything():
    limit = csv_service.MAX_UPLOAD_BYTES
    fake = _FakeUpload(limit * 4)

    with pytest.raises(Exception) as exc:
        asyncio.run(uploads_module.read_upload_limited(fake))

    assert getattr(exc.value, "status_code", None) == 413
    # At most one chunk beyond the cap is read; the rest of the body never is.
    assert fake.bytes_read <= limit + uploads_module._UPLOAD_CHUNK_BYTES
    assert fake.bytes_read < limit * 4


def test_streaming_upload_limit_returns_small_files_unchanged():
    payload = b"a,b\n1,2\n"

    class SmallUpload:
        """One-shot upload that yields the real bytes, then EOF."""

        def __init__(self) -> None:
            self._sent = False

        async def read(self, size: int = -1) -> bytes:
            if self._sent:
                return b""
            self._sent = True
            return payload

    assert asyncio.run(uploads_module.read_upload_limited(SmallUpload())) == payload
