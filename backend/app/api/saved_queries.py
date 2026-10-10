"""Saved queries CRUD with ownership enforcement."""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.deps import get_current_user
from app.core.errors import ApiError
from app.db.session import get_db
from app.models import SavedQuery, User
from app.schemas import SavedQueryIn, SavedQueryPatch

router = APIRouter()


def _serialize(row: SavedQuery) -> dict:
    try:
        tags = json.loads(row.tags or "[]")
    except json.JSONDecodeError:
        tags = []
    return {
        "id": row.id,
        "connection_id": row.connection_id,
        "title": row.title,
        "description": row.description,
        "natural_language_question": row.natural_language_question,
        "sql_query": row.sql_query,
        "tags": tags if isinstance(tags, list) else [],
        "is_favorite": row.is_favorite,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


@router.get("")
def list_saved(
    q: str | None = Query(default=None, max_length=200),
    favorite: bool | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    filters = [SavedQuery.user_id == user.id]
    if q:
        like = f"%{q.strip()}%"
        filters.append(
            (SavedQuery.title.ilike(like))
            | (SavedQuery.description.ilike(like))
            | (SavedQuery.sql_query.ilike(like))
            | (SavedQuery.natural_language_question.ilike(like))
        )
    if favorite is not None:
        filters.append(SavedQuery.is_favorite.is_(favorite))
    total = db.execute(select(func.count()).select_from(SavedQuery).where(*filters)).scalar_one()
    rows = (
        db.execute(
            select(SavedQuery)
            .where(*filters)
            .order_by(SavedQuery.updated_at.desc())
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


@router.post("", status_code=201)
def create_saved(
    payload: SavedQueryIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    row = SavedQuery(
        user_id=user.id,
        connection_id=payload.connection_id,
        title=payload.title.strip(),
        description=payload.description,
        natural_language_question=payload.natural_language_question,
        sql_query=payload.sql_query,
        tags=json.dumps(payload.tags),
        is_favorite=payload.is_favorite,
    )
    db.add(row)
    db.commit()
    return {"success": True, "item": _serialize(row)}


def _owned(db: Session, user: User, query_id: str) -> SavedQuery:
    row = db.get(SavedQuery, query_id)
    if row is None or row.user_id != user.id:
        raise ApiError(404, "not_found", "Saved query not found.")
    return row


@router.get("/{query_id}")
def get_saved(
    query_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    return {"success": True, "item": _serialize(_owned(db, user, query_id))}


@router.patch("/{query_id}")
def patch_saved(
    query_id: str,
    payload: SavedQueryPatch,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    row = _owned(db, user, query_id)
    data = payload.model_dump(exclude_unset=True)
    if "tags" in data and data["tags"] is not None:
        row.tags = json.dumps(data.pop("tags"))
    for key, value in data.items():
        setattr(row, key, value)
    db.commit()
    return {"success": True, "item": _serialize(row)}


@router.delete("/{query_id}")
def delete_saved(
    query_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    row = _owned(db, user, query_id)
    db.delete(row)
    db.commit()
    return {"success": True}
