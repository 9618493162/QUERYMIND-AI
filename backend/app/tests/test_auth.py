"""Authentication, session and authorization tests."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.tests.conftest import csrf


def _register(client: TestClient, email: str = "user@querymind.dev", password: str = "Sup3rSecret!") -> dict:
    client.get("/api/health")
    return {"name": "User", "email": email, "password": password}


def test_register_login_logout_flow(client: TestClient):
    client.get("/api/health")
    resp = client.post("/api/auth/register", json=_register(client), headers=csrf(client))
    assert resp.status_code == 201
    body = resp.json()
    assert body["success"] is True
    assert body["user"]["email"] == "user@querymind.dev"
    assert "password" not in str(body)

    me = client.get("/api/auth/me")
    assert me.status_code == 200
    assert me.json()["user"]["email"] == "user@querymind.dev"

    out = client.post("/api/auth/logout", headers=csrf(client))
    assert out.status_code == 200
    assert client.get("/api/auth/me").status_code == 401

    login = client.post(
        "/api/auth/login",
        json={"email": "user@querymind.dev", "password": "Sup3rSecret!"},
        headers=csrf(client),
    )
    assert login.status_code == 200
    assert client.get("/api/auth/me").status_code == 200


def test_duplicate_email_rejected(client: TestClient):
    client.get("/api/health")
    first = client.post("/api/auth/register", json=_register(client), headers=csrf(client))
    assert first.status_code == 201
    client.post("/api/auth/logout", headers=csrf(client))
    dup = client.post("/api/auth/register", json=_register(client), headers=csrf(client))
    assert dup.status_code == 409
    assert dup.json()["error"]["code"] == "email_taken"


def test_wrong_password_rejected(client: TestClient):
    client.get("/api/health")
    client.post("/api/auth/register", json=_register(client), headers=csrf(client))
    client.post("/api/auth/logout", headers=csrf(client))
    bad = client.post(
        "/api/auth/login",
        json={"email": "user@querymind.dev", "password": "not-the-password"},
        headers=csrf(client),
    )
    assert bad.status_code == 401
    assert bad.json()["error"]["code"] == "invalid_credentials"


def test_weak_password_rejected(client: TestClient):
    client.get("/api/health")
    resp = client.post(
        "/api/auth/register",
        json={"name": "A", "email": "weak@querymind.dev", "password": "short"},
        headers=csrf(client),
    )
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "validation_error"


def test_unauthenticated_requests_rejected(client: TestClient):
    client.get("/api/health")
    assert client.get("/api/connections").status_code == 401
    assert client.get("/api/history").status_code == 401
    assert client.get("/api/saved-queries").status_code == 401
    assert client.get("/api/analytics/overview").status_code == 401
    # POST without a session: CSRF runs first for cookie-less clients, so 403 is
    # also acceptable; a session-less browser client ends up at 401.
    assert client.post("/api/query/generate", json={}).status_code in (401, 403, 422)


def test_csrf_required_for_mutations(client: TestClient):
    client.get("/api/health")
    resp = client.post(
        "/api/auth/register",
        json=_register(client),
        headers={"X-CSRF-Token": "wrong-token"},
    )
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "csrf_failed"


def test_password_never_returned_and_hash_is_argon2(client: TestClient):
    client.get("/api/health")
    client.post("/api/auth/register", json=_register(client), headers=csrf(client))
    from sqlalchemy import select

    from app.db.session import get_engine
    from app.models import User

    with get_engine().connect() as conn:
        row = conn.execute(select(User.password_hash, User.email)).first()
    assert row is not None
    password_hash, email = row[0], row[1]
    assert email == "user@querymind.dev"
    assert password_hash.startswith("$argon2")
    assert "Sup3rSecret" not in password_hash


def test_rate_limiting_on_login(client: TestClient):
    client.get("/api/health")
    statuses = []
    for _ in range(15):
        r = client.post(
            "/api/auth/login",
            json={"email": "nobody@querymind.dev", "password": "wrong-password"},
            headers=csrf(client),
        )
        statuses.append(r.status_code)
    assert 429 in statuses, f"expected rate limiting, got {statuses}"


def _production_settings(**overrides):
    """A valid production Settings object with individual values overridable."""
    from app.core.config import Settings

    base = dict(
        app_env="production",
        app_secret_key="prod-secret-key-abc123notforrealdeploy",
        encryption_key="test-encryption-key-0123456789abcdef",
        frontend_origin="https://app.example.com",
    )
    base.update(overrides)
    return Settings(**base)


def test_production_requires_https_origin():
    """Production must not silently run with an insecure frontend origin."""
    prod_http = _production_settings(frontend_origin="http://example.com")
    assert prod_http.is_production
    problems = prod_http.validate_for_runtime()
    assert any("https://" in p for p in problems), problems


def test_production_rejects_wildcard_and_loopback_origins():
    wildcard = _production_settings(frontend_origin="*")
    assert any("'*'" in p for p in wildcard.validate_production_security())

    loopback = _production_settings(frontend_origin="https://localhost:5173")
    assert any("localhost" in p for p in loopback.validate_production_security())


def test_production_accepts_explicit_https_origins():
    prod = _production_settings(
        frontend_origin="https://app.example.com,https://admin.example.com/"
    )
    assert prod.cors_origins == ["https://app.example.com", "https://admin.example.com"]
    assert prod.validate_production_security() == []


def test_production_rejects_insecure_cookie_overrides():
    insecure = _production_settings(cookie_secure=False)
    assert any("Secure" in p for p in insecure.validate_production_security())

    samesite_none = _production_settings(cookie_secure=True, cookie_samesite="none")
    assert samesite_none.cookies_are_secure is True
    assert samesite_none.validate_production_security() == []


def test_development_is_not_gated_on_https():
    from app.core.config import Settings

    dev = Settings(app_env="development", frontend_origin="http://localhost:5173")
    assert dev.is_production is False
    assert dev.cookies_are_secure is False
    assert dev.validate_production_security() == []


def test_secure_cookies_are_configured_for_production(monkeypatch):
    """In production the session and CSRF cookies must be marked Secure."""
    from app.core import security as security_module
    from app.core.security import csrf_cookie_kwargs, session_cookie_kwargs

    # The test environment is not production, so cookies are not Secure.
    assert session_cookie_kwargs()["secure"] is False, session_cookie_kwargs()
    assert csrf_cookie_kwargs()["secure"] is False, csrf_cookie_kwargs()

    monkeypatch.setattr(security_module.settings, "app_env", "production")

    assert session_cookie_kwargs()["secure"] is True, session_cookie_kwargs()
    assert session_cookie_kwargs()["httponly"] is True
    assert session_cookie_kwargs()["samesite"] == "lax"
    assert csrf_cookie_kwargs()["secure"] is True, csrf_cookie_kwargs()
    # The CSRF cookie must stay readable by the SPA to echo it in a header.
    assert csrf_cookie_kwargs()["httponly"] is False


def test_ownership_isolation_between_users(client: TestClient):
    # user A
    client.get("/api/health")
    client.post(
        "/api/auth/register",
        json={"name": "A", "email": "a@querymind.dev", "password": "Sup3rSecret!"},
        headers=csrf(client),
    )
    conn_a = client.post(
        "/api/connections",
        headers=csrf(client),
        json={
            "name": "A connection",
            "host": "localhost",
            "port": 5433,
            "database_name": "analytics",
            "username": "analytics_owner",
            "password": "analytics_password_change_me",
            "ssl_mode": "disable",
        },
    )
    assert conn_a.status_code == 201, conn_a.text
    conn_id = conn_a.json()["connection"]["id"]
    client.post("/api/auth/logout", headers=csrf(client))

    # user B
    client.post("/api/auth/register", json={"name": "B", "email": "b@querymind.dev", "password": "Sup3rSecret!"}, headers=csrf(client))
    listing = client.get("/api/connections")
    assert listing.status_code == 200
    assert listing.json()["items"] == []
    assert client.get(f"/api/connections/{conn_id}").status_code == 404
    assert (
        client.delete(f"/api/connections/{conn_id}", headers=csrf(client)).status_code == 404
    )
