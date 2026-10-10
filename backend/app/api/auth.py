"""Authentication: register, login, logout, current user."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.deps import get_current_user
from app.core.errors import ApiError
from app.core.rate_limit import rate_limit
from app.core.security import (
    csrf_cookie_kwargs,
    hash_password,
    hash_session_token,
    new_csrf_token,
    new_session_token,
    password_needs_rehash,
    session_cookie_kwargs,
    session_expiry,
    verify_password,
)
from app.db.session import get_db
from app.models import User, UserSession, UserSettings
from app.schemas import LoginIn, RegisterIn, UserOut

router = APIRouter()


def _issue_session(response: Response, db: Session, user: User) -> None:
    token = new_session_token()
    csrf = new_csrf_token()
    db.add(
        UserSession(
            user_id=user.id,
            token_hash=hash_session_token(token),
            expires_at=session_expiry(),
        )
    )
    # purge expired sessions for this user
    db.execute(
        delete(UserSession).where(
            UserSession.user_id == user.id,
            UserSession.expires_at < datetime.now(timezone.utc),
        )
    )
    response.set_cookie(settings.session_cookie, token, **session_cookie_kwargs())
    response.set_cookie(settings.csrf_cookie, csrf, **csrf_cookie_kwargs())


def _user_out(user: User) -> dict:
    return {
        "id": user.id,
        "name": user.name,
        "email": user.email,
        "created_at": user.created_at.isoformat() if user.created_at else None,
    }


@router.post("/register", status_code=201)
def register(payload: RegisterIn, request: Request, response: Response, db: Session = Depends(get_db)) -> dict:
    rate_limit(request, "auth-register", settings.auth_rate_limit_per_minute)
    email = payload.email.lower().strip()
    existing = db.execute(select(User).where(User.email == email)).scalar_one_or_none()
    if existing is not None:
        raise ApiError(409, "email_taken", "An account with this email already exists.")
    user = User(name=payload.name.strip(), email=email, password_hash=hash_password(payload.password))
    db.add(user)
    db.flush()
    db.add(UserSettings(user_id=user.id))
    db.flush()
    _issue_session(response, db, user)
    # Commit before responding: the client's very next request is usually
    # GET /api/auth/me, which must already see the new session row.
    db.commit()
    return {"success": True, "user": _user_out(user)}


@router.post("/login")
def login(payload: LoginIn, request: Request, response: Response, db: Session = Depends(get_db)) -> dict:
    rate_limit(request, "auth-login", settings.auth_rate_limit_per_minute)
    email = payload.email.lower().strip()
    user = db.execute(select(User).where(User.email == email)).scalar_one_or_none()
    if user is None or not verify_password(user.password_hash, payload.password):
        raise ApiError(401, "invalid_credentials", "Incorrect email or password.")
    if password_needs_rehash(user.password_hash):
        user.password_hash = hash_password(payload.password)
    _issue_session(response, db, user)
    db.commit()
    return {"success": True, "user": _user_out(user)}


@router.post("/logout")
def logout(request: Request, response: Response, db: Session = Depends(get_db)) -> dict:
    token = request.cookies.get(settings.session_cookie)
    if token:
        db.execute(
            delete(UserSession).where(UserSession.token_hash == hash_session_token(token))
        )
    db.commit()
    # Only the session cookie is cleared; the CSRF cookie stays so the next
    # login can be submitted immediately without a bootstrap round-trip.
    response.delete_cookie(settings.session_cookie, path="/")
    return {"success": True}


@router.get("/me")
def me(user: User = Depends(get_current_user)) -> dict:
    return {"success": True, "user": _user_out(user)}
