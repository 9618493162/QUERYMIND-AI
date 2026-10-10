"""Query history: list, get, delete — with ownership checks."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.core.deps import get_current_user
from app.core.errors import ApiError
from app.db.session import get_db
from app.models import QueryHistory, User
from app.schemas import HistoryOut

router = APIRouter()


def _serialize(row: QueryHistory) -> dict:
    return {
        "id": row.id,
        "connection_id": row.connection_id,
        "conversation_id": row.conversation_id,
        "question": row.question,
        "generated_sql": row.generated_sql,
        "execution_status": row.execution_status,
        "execution_time_ms": row.execution_time_ms,
        "row_count": row.row_count,
        "error_message": row.error_message,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


@router.get("")
def list_history(
    q: str | None = Query(default=None, max_length=200),
    status: str | None = Query(default=None, max_length=32),
    connection_id: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    filters = [QueryHistory.user_id == user.id]
    if q:
        like = f"%{q.strip()}%"
        filters.append(
            (QueryHistory.question.ilike(like)) | (QueryHistory.generated_sql.ilike(like))
        )
    if status:
        filters.append(QueryHistory.execution_status == status)
    if connection_id:
        filters.append(QueryHistory.connection_id == connection_id)

    total = db.execute(select(func.count()).select_from(QueryHistory).where(*filters)).scalar_one()
    rows = (
        db.execute(
            select(QueryHistory)
            .where(*filters)
            .order_by(QueryHistory.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        .scalars()
        .all()
    )
    return {
        "success": True,
        "items": [_serialize(r) for r in rows],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.get("/{query_id}")
def get_history_item(
    query_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    row = db.get(QueryHistory, query_id)
    if row is None or row.user_id != user.id:
        raise ApiError(404, "not_found", "History entry not found.")
    return {"success": True, "item": _serialize(row)}


@router.delete("/{query_id}")
def delete_history_item(
    query_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    row = db.get(QueryHistory, query_id)
    if row is None or row.user_id != user.id:
        raise ApiError(404, "not_found", "History entry not found.")
    db.delete(row)
    db.commit()
    return {"success": True}
