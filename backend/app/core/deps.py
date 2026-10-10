"""FastAPI dependencies: current user, CSRF enforcement, ownership checks."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.errors import ApiError
from app.core.security import csrf_tokens_match, hash_session_token
from app.db.session import get_db
from app.models import User, UserSession


def _session_from_request(request: Request, db: Session) -> User | None:
    token = request.cookies.get(settings.session_cookie)
    if not token:
        return None
    token_hash = hash_session_token(token)
    row = db.execute(
        select(UserSession).where(
            UserSession.token_hash == token_hash,
            UserSession.revoked_at.is_(None),
        )
    ).scalar_one_or_none()
    if row is None:
        return None
    expires = row.expires_at
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    if expires < datetime.now(timezone.utc):
        return None
    return db.get(User, row.user_id)


def get_current_user(request: Request, db: Session = Depends(get_db)) -> User:
    user = _session_from_request(request, db)
    if user is None:
        raise ApiError(401, "unauthorized", "You must be signed in to perform this action.")
    return user


def enforce_csrf(request: Request) -> None:
    """Double-submit CSRF check for state-changing requests.

    A CSRF cookie is issued on every response when missing (see main.py), so a
    browser client always has a token to echo in the ``X-CSRF-Token`` header.
    """
    if request.method in ("GET", "HEAD", "OPTIONS"):
        return
    cookie = request.cookies.get(settings.csrf_cookie)
    header = request.headers.get(settings.csrf_header)
    if not csrf_tokens_match(cookie, header):
        raise ApiError(
            403,
            "csrf_failed",
            "Invalid or missing CSRF token. Refresh the page and retry.",
        )


def owns_or_404(user: User, owner_id: str | None, resource: str = "Resource") -> None:
    if owner_id != user.id:
        raise ApiError(404, "not_found", f"{resource} not found.")
