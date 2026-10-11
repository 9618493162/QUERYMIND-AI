"""CSV upload: parsing, sanitization, dataset creation and access control."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.services import csv_service
from app.tests.conftest import csrf


def test_sanitize_identifier():
    assert csv_service.sanitize_identifier("My Data Set!") == "my_data_set"
    assert csv_service.sanitize_identifier("123abc") == "col_123abc"
    assert csv_service.sanitize_identifier("résumé") == "resume"
    assert len(csv_service.sanitize_identifier("x" * 200)) <= 63
    # SQL injection attempt in a column name is neutralized
    safe = csv_service.sanitize_identifier('a"; DROP TABLE users;--')
    assert '"' not in safe and ";" not in safe and " " not in safe


def test_parse_csv_infers_types():
    content = b"id,name,price,active,joined\n1,Alice,10.5,true,2024-01-01\n2,Bob,20.0,false,2024-02-01\n"
    df, columns = csv_service.parse_csv(content, "people.csv")
    types = {c["name"]: c["type"] for c in columns}
    assert types["id"] == "bigint"
    assert types["name"] == "text"
    assert types["price"] == "double precision"
    assert types["active"] == "boolean"
    assert len(df) == 2


def test_parse_csv_rejects_oversized_file():
    big = b"a,b\n" + b"1,2\n" * 400_000
    with pytest.raises(Exception) as exc:
        csv_service.parse_csv(big, "big.csv")
    assert getattr(exc.value, "code", None) in {413, "file_too_large", "too_many_rows"}


def test_parse_csv_rejects_empty_and_invalid():
    with pytest.raises(Exception):
        csv_service.parse_csv(b"", "empty.csv")
    with pytest.raises(Exception):
        csv_service.parse_csv(b"\x00\x01\x02\x03 not really csv", "bin.csv")


def test_upload_preview_and_dataset(
    auth_client: TestClient, analytics_connection_payload: dict
):
    create = auth_client.post(
        "/api/connections", headers=csrf(auth_client), json=analytics_connection_payload
    )
    conn_id = create.json()["connection"]["id"]

    content = b"region,amount\nNorth,100\nSouth,250\n"
    preview = auth_client.post(
        "/api/uploads/preview",
        headers=csrf(auth_client),
        files={"file": ("sales.csv", content, "text/csv")},
    )
    assert preview.status_code == 200, preview.text
    body = preview.json()
    assert body["row_count"] == 2
    assert body["columns"][0]["name"] == "region"

    dataset = auth_client.post(
        "/api/uploads",
        headers=csrf(auth_client),
        data={"connection_id": conn_id, "table_name": "Regional Sales!", "persistent": "false"},
        files={"file": ("sales.csv", content, "text/csv")},
    )
    assert dataset.status_code == 201, dataset.text
    ds = dataset.json()["dataset"]
    assert ds["qualified_name"] == "querymind_uploads.regional_sales"
    assert ds["row_count"] == 2
    assert ds["persistent"] is False

    # The dataset is queryable through the normal pipeline.
    exe = auth_client.post(
        "/api/query/execute",
        headers=csrf(auth_client),
        json={
            "connection_id": conn_id,
            "sql": 'SELECT region, amount FROM querymind_uploads.regional_sales ORDER BY amount DESC',
            "question": "uploaded data",
        },
    )
    assert exe.status_code == 200, exe.text
    assert exe.json()["rows"][0][0] == "South"

    # Cleanup drops the table and the metadata row.
    delete = auth_client.delete(f"/api/uploads/{ds['id']}", headers=csrf(auth_client))
    assert delete.status_code == 200


def test_upload_requires_authentication(client: TestClient):
    resp = client.post(
        "/api/uploads/preview",
        files={"file": ("a.csv", b"a,b\n1,2\n", "text/csv")},
    )
    # CSRF dependency runs first for cookie-less clients (403); browser clients
    # with a CSRF cookie but no session get 401.
    assert resp.status_code in (401, 403)


def _oversized_csv() -> bytes:
    """Build a CSV comfortably past MAX_UPLOAD_BYTES (4 bytes per row)."""
    payload = b"a,b\n" + b"1,2\n" * 1_600_000  # ~6.4 MB
    assert len(payload) > csv_service.MAX_UPLOAD_BYTES
    return payload


def test_oversized_upload_is_rejected_while_streaming(auth_client: TestClient):
    """The 5 MB cap is enforced at the edge of the request, not after buffering.

    /api/uploads is deliberately exempt from the generic 2 MB body cap, so this
    is the check that actually protects the server from a huge upload.
    """
    oversized = _oversized_csv()

    resp = auth_client.post(
        "/api/uploads/preview",
        headers=csrf(auth_client),
        files={"file": ("huge.csv", oversized, "text/csv")},
    )

    assert resp.status_code == 413
    body = resp.json()
    assert body["error"]["code"] == "file_too_large"
    assert "5 MB" in body["error"]["message"]


def test_oversized_dataset_creation_is_rejected(auth_client: TestClient, analytics_connection_payload: dict):
    create = auth_client.post(
        "/api/connections", headers=csrf(auth_client), json=analytics_connection_payload
    )
    conn_id = create.json()["connection"]["id"]

    oversized = _oversized_csv()
    resp = auth_client.post(
        "/api/uploads",
        headers=csrf(auth_client),
        data={"connection_id": conn_id, "table_name": "too_big", "persistent": "false"},
        files={"file": ("huge.csv", oversized, "text/csv")},
    )

    assert resp.status_code == 413
    assert resp.json()["error"]["code"] == "file_too_large"


def test_upload_at_the_limit_is_accepted(client: TestClient):
    """A file exactly at the cap must pass (the boundary is not off by one)."""
    from app.api.uploads import read_upload_limited

    payload = b"a,b\n" + b"1,2\n" * ((csv_service.MAX_UPLOAD_BYTES - 4) // 4)
    payload = payload[: csv_service.MAX_UPLOAD_BYTES]
    assert len(payload) == csv_service.MAX_UPLOAD_BYTES

    class ExactUpload:
        def __init__(self) -> None:
            self._sent = False

        async def read(self, size: int = -1) -> bytes:
            if self._sent:
                return b""
            self._sent = True
            return payload

    import asyncio

    assert asyncio.run(read_upload_limited(ExactUpload())) == payload
