"""CSV upload: preview and materialize an analytical dataset."""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.deps import get_current_user
from app.core.errors import ApiError
from app.core.rate_limit import rate_limit
from app.db.session import get_db
from app.models import UploadedDataset, User
from app.services import connection_service, csv_service, schema_service

router = APIRouter()

# Read one chunk at a time so an oversized upload is rejected WHILE it is still
# arriving, instead of after the whole body has been buffered in memory.
_UPLOAD_CHUNK_BYTES = 64 * 1024


async def read_upload_limited(file: UploadFile) -> bytes:
    """Read an upload, enforcing the CSV size cap while streaming.

    Raises ``ApiError(413)`` as soon as the limit is exceeded, so a client
    cannot make the server buffer an arbitrarily large body. ``parse_csv``
    repeats the check as defence in depth.
    """
    limit = csv_service.MAX_UPLOAD_BYTES
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = await file.read(_UPLOAD_CHUNK_BYTES)
        if not chunk:
            break
        total += len(chunk)
        if total > limit:
            raise ApiError(
                413,
                "file_too_large",
                f"CSV files are limited to {limit // (1024 * 1024)} MB.",
            )
        chunks.append(chunk)
    return b"".join(chunks)


@router.post("/preview")
async def preview_csv(
    request: Request,
    file: UploadFile = File(...),
    user: User = Depends(get_current_user),
) -> dict:
    rate_limit(request, "csv-upload", 10)
    content = await read_upload_limited(file)
    df, columns = csv_service.parse_csv(content, file.filename or "upload.csv")
    preview_rows = [_preview_row(row) for row in df.head(20).itertuples(index=False, name=None)]
    return {
        "success": True,
        "columns": columns,
        "row_count": len(df),
        "preview_rows": preview_rows,
        "suggested_table": csv_service.sanitize_identifier(
            (file.filename or "dataset").rsplit(".", 1)[0]
        ),
    }


def _preview_row(row: tuple) -> list:
    """JSON-safe preview row: NaN -> None, numpy scalars -> python scalars."""
    out: list = []
    for v in row:
        try:
            import pandas as pd

            if pd.isna(v):
                out.append(None)
                continue
        except Exception:
            pass
        out.append(v.item() if hasattr(v, "item") else v)
    return out


@router.get("")
def list_datasets(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    rows = (
        db.execute(
            select(UploadedDataset)
            .where(UploadedDataset.user_id == user.id)
            .order_by(UploadedDataset.created_at.desc())
        )
        .scalars()
        .all()
    )
    return {
        "success": True,
        "items": [
            {
                "id": r.id,
                "original_filename": r.original_filename,
                "table_name": r.table_name,
                "qualified_name": f"{csv_service.UPLOAD_SCHEMA}.{r.table_name}",
                "persistent": r.persistent,
                "row_count": r.row_count,
                "columns": json.loads(r.columns_json or "[]"),
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ],
    }


@router.post("", status_code=201)
async def create_dataset(
    request: Request,
    file: UploadFile = File(...),
    connection_id: str = Form(...),
    table_name: str = Form(...),
    persistent: bool = Form(False),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    rate_limit(request, "csv-upload", 10)
    conn = connection_service.get_owned_connection(db, user, connection_id)
    content = await read_upload_limited(file)
    df, columns = csv_service.parse_csv(content, file.filename or "upload.csv")

    engine = connection_service.engine_for_connection(conn, read_only=False)
    try:
        schema_service.assert_connection_allowed(conn.host)
        result = csv_service.create_dataset(
            engine,
            df=df,
            columns=columns,
            table_name=table_name,
            persistent=persistent,
            user_id=user.id,
        )
    except ApiError:
        raise
    except Exception as exc:
        raise ApiError(
            502,
            "dataset_creation_failed",
            f"Could not create the dataset in the connected database: "
            f"{exc.__class__.__name__}.",
        ) from exc
    finally:
        engine.dispose()

    row = UploadedDataset(
        user_id=user.id,
        original_filename=file.filename or "upload.csv",
        table_name=result["table"],
        persistent=persistent,
        columns_json=json.dumps(columns),
        row_count=result["row_count"],
    )
    db.add(row)
    db.commit()
    schema_service.invalidate(connection_id)

    return {
        "success": True,
        "dataset": {
            "id": row.id,
            "qualified_name": result["qualified_name"],
            "table_name": result["table"],
            "persistent": persistent,
            "row_count": result["row_count"],
            "columns": columns,
            "note": (
                "Persistent dataset: stored in your database until you delete it."
                if persistent
                else "Temporary dataset: delete it when you are done analyzing."
            ),
        },
    }


@router.delete("/{dataset_id}")
def delete_dataset(
    dataset_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    row = db.get(UploadedDataset, dataset_id)
    if row is None or row.user_id != user.id:
        raise ApiError(404, "not_found", "Dataset not found.")
    # Drop the table from the user's connections where it might live.
    conns = connection_service.list_connections(db, user)
    for conn in conns:
        if row.table_name:
            engine = connection_service.engine_for_connection(conn, read_only=False)
            try:
                csv_service.drop_dataset(engine, row.table_name)
            except Exception:
                pass
            finally:
                engine.dispose()
    db.delete(row)
    db.commit()
    return {"success": True}
