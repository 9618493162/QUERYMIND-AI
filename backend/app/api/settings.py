"""User settings (theme, default chart, default row limit)."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.deps import get_current_user
from app.db.session import get_db
from app.models import User, UserSettings
from app.schemas import SettingsIn

router = APIRouter()


def _out(row: UserSettings) -> dict:
    return {
        "theme": row.theme,
        "default_chart_type": row.default_chart_type,
        "default_row_limit": row.default_row_limit,
    }


@router.get("")
def get_settings_view(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    row = db.execute(
        select(UserSettings).where(UserSettings.user_id == user.id)
    ).scalar_one_or_none()
    if row is None:
        row = UserSettings(user_id=user.id)
        db.add(row)
        db.commit()
    return {"success": True, "settings": _out(row)}


@router.patch("")
def update_settings(
    payload: SettingsIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    row = db.execute(
        select(UserSettings).where(UserSettings.user_id == user.id)
    ).scalar_one_or_none()
    if row is None:
        row = UserSettings(user_id=user.id)
        db.add(row)
    row.theme = payload.theme
    row.default_chart_type = payload.default_chart_type
    row.default_row_limit = payload.default_row_limit
    db.commit()
    return {"success": True, "settings": _out(row)}
