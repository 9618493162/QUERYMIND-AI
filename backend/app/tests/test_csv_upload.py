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
