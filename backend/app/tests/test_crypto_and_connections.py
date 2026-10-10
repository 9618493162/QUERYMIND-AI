"""Credential encryption and connection management tests."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.services import crypto
from app.tests.conftest import csrf


def test_encrypt_decrypt_roundtrip():
    token = crypto.encrypt_secret("s3cret-password")
    assert token != "s3cret-password"
    assert crypto.decrypt_secret(token) == "s3cret-password"


def test_ciphertext_is_authenticated():
    token = crypto.encrypt_secret("s3cret-password")
    tampered = token[:-4] + ("AAAA" if not token.endswith("AAAA") else "BBBB")
    with pytest.raises(Exception):
        crypto.decrypt_secret(tampered)


def test_missing_encryption_key_fails_safely(monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "encryption_key", "")
    crypto.reset_cache()
    try:
        available, reason = crypto.encryption_available()
        assert available is False
        assert reason and "ENCRYPTION_KEY" in reason
        with pytest.raises(crypto.EncryptionConfigError):
            crypto.get_fernet()
    finally:
        monkeypatch.setattr(settings, "encryption_key", "test-encryption-key-0123456789abcdef")
        crypto.reset_cache()


def test_connection_password_never_in_response(auth_client: TestClient, analytics_connection_payload: dict):
    resp = auth_client.post("/api/connections", headers=csrf(auth_client), json=analytics_connection_payload)
    assert resp.status_code == 201, resp.text
    created = resp.json()["connection"]
    assert "password" not in created
    assert created["has_password"] is True
    assert "analytics_password_change_me" not in resp.text

    listing = auth_client.get("/api/connections")
    assert "analytics_password_change_me" not in listing.text

    single = auth_client.get(f"/api/connections/{created['id']}")
    assert "analytics_password_change_me" not in single.text


def test_connection_crud(auth_client: TestClient, analytics_connection_payload: dict):
    create = auth_client.post("/api/connections", headers=csrf(auth_client), json=analytics_connection_payload)
    assert create.status_code == 201
    conn_id = create.json()["connection"]["id"]

    dup = auth_client.post("/api/connections", headers=csrf(auth_client), json=analytics_connection_payload)
    assert dup.status_code == 409

    listing = auth_client.get("/api/connections")
    assert listing.status_code == 200
    assert len(listing.json()["items"]) == 1

    delete = auth_client.delete(f"/api/connections/{conn_id}", headers=csrf(auth_client))
    assert delete.status_code == 200
    assert auth_client.get("/api/connections").json()["items"] == []


def test_connection_test_endpoint_real_db(auth_client: TestClient, analytics_connection_payload: dict):
    resp = auth_client.post(
        "/api/connections/test",
        headers=csrf(auth_client),
        json={**analytics_connection_payload, "database_type": "postgresql"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["success"] is True, body
    assert body["server_version"]


def test_connection_test_reports_real_failure(auth_client: TestClient):
    resp = auth_client.post(
        "/api/connections/test",
        headers=csrf(auth_client),
        json={
            "name": "bad",
            "database_type": "postgresql",
            "host": "localhost",
            "port": 1,
            "database_name": "nope",
            "username": "nope",
            "password": "nope",
            "ssl_mode": "disable",
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is False
    assert body["message"]


def test_schema_inspection_real_db(auth_client: TestClient, analytics_connection_payload: dict):
    create = auth_client.post("/api/connections", headers=csrf(auth_client), json=analytics_connection_payload)
    conn_id = create.json()["connection"]["id"]
    resp = auth_client.get(f"/api/connections/{conn_id}/schema?refresh=true")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    names = {t["name"] for t in body["tables"]}
    assert {"orders", "customers", "products", "order_items", "regions"} <= names
    views = [t for t in body["tables"] if t["kind"] == "view"]
    assert any(v["name"] == "monthly_sales" for v in views), "view discovery failed"
    # relationships from FKs
    assert any(r["table"] == "order_items" for r in body["relationships"])


def test_prohibited_destination_rejected(auth_client: TestClient):
    resp = auth_client.post(
        "/api/connections/test",
        headers=csrf(auth_client),
        json={
            "name": "metadata",
            "database_type": "postgresql",
            "host": "169.254.169.254",
            "port": 5432,
            "database_name": "x",
            "username": "x",
            "password": "x",
            "ssl_mode": "disable",
        },
    )
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] in {"destination_not_allowed"}
