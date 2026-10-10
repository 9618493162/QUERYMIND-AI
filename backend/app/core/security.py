"""Password hashing, session cookies and CSRF protection.

Authentication uses an opaque session token stored in an HttpOnly cookie.
The token is random (256 bits); only its SHA-256 hash is persisted server-side,
so a database leak does not expose usable sessions.
CSRF uses a double-submit token in a readable cookie that must be echoed in the
``X-CSRF-Token`` header on every state-changing request.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from app.core.config import settings

_hasher = PasswordHasher(time_cost=3, memory_cost=64 * 1024, parallelism=2, hash_len=32, salt_len=16)

SESSION_TTL_DAYS = 7


# --- passwords ---------------------------------------------------------------

def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False
    except Exception:
        return False


def password_needs_rehash(password_hash: str) -> bool:
    try:
        return _hasher.check_needs_rehash(password_hash)
    except Exception:
        return False


# --- sessions ----------------------------------------------------------------

def new_session_token() -> str:
    return secrets.token_urlsafe(32)


def hash_session_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def new_csrf_token() -> str:
    return secrets.token_urlsafe(24)


def csrf_tokens_match(a: str | None, b: str | None) -> bool:
    if not a or not b:
        return False
    return hmac.compare_digest(a, b)


def session_expiry() -> datetime:
    return datetime.now(timezone.utc) + timedelta(days=SESSION_TTL_DAYS)


def session_cookie_kwargs() -> dict:
    return dict(
        httponly=True,
        secure=settings.is_production,
        samesite="lax",
        max_age=SESSION_TTL_DAYS * 24 * 3600,
        path="/",
    )


def csrf_cookie_kwargs() -> dict:
    # Readable by the frontend so it can echo the token in headers.
    return dict(
        httponly=False,
        secure=settings.is_production,
        samesite="lax",
        max_age=SESSION_TTL_DAYS * 24 * 3600,
        path="/",
    )
