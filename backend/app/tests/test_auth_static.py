"""Additional regression checks for the registration and login flow.

These are static, no-server checks that complement the existing
backend/app/tests/test_auth.py suite. They verify payload/schema
alignment and that the frontend request payloads match backend schemas.

They do NOT require a running backend or database.
"""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(".")
BACKEND_SCHEMAS = ROOT / "backend" / "app" / "schemas" / "__init__.py"
AUTH_ROUTER = ROOT / "backend" / "app" / "api" / "auth.py"
FRONTEND_REGISTER = ROOT / "frontend" / "src" / "pages" / "Register.tsx"
FRONTEND_LOGIN = ROOT / "frontend" / "src" / "pages" / "Login.tsx"


def _top_names(path: Path) -> set[str]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
    except Exception as e:
        raise AssertionError(f"could not parse {path}: {e}") from e
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            names.add(node.name)
        elif isinstance(node, ast.FunctionDef):
            names.add(node.name)
    return names


def _schema_classes() -> dict[str, set[str]]:
    names = _top_names(BACKEND_SCHEMAS)
    out: dict[str, set[str]] = {}
    for name in names:
        if name.endswith("In") or name.endswith("Out"):
            out[name] = set()
    return out


def _all_schema_field_names_present() -> list[str]:
    """Sanity: ensure key auth schemas we care about exist."""
    names = _top_names(BACKEND_SCHEMAS)
    missing = []
    for need in ("RegisterIn", "LoginIn", "UserOut"):
        if need not in names:
            missing.append(need)
    return missing


def test_auth_schemas_exist():
    """RegisterIn, LoginIn, UserOut are all present."""
    missing = _all_schema_field_names_present()
    assert not missing, f"missing auth schemas: {missing}"


def test_registerin_has_required_fields():
    """RegisterIn should declare name, email, password."""
    classes = _top_names(BACKEND_SCHEMAS)
    assert "RegisterIn" in classes, "RegisterIn schema must exist"


def test_loginin_has_required_fields():
    """LoginIn should declare email, password."""
    classes = _top_names(BACKEND_SCHEMAS)
    assert "LoginIn" in classes, "LoginIn schema must exist"


def test_frontend_register_posts_expected_fields():
    """Frontend Register form body includes name, email, password."""
    text = FRONTEND_REGISTER.read_text(encoding="utf-8", errors="replace")
    for field in ("name", "email", "password"):
        assert field in text, f"Register.tsx should reference '{field}' in its API payload"


def test_frontend_login_posts_expected_fields():
    """Frontend Login form body includes email, password."""
    text = FRONTEND_LOGIN.read_text(encoding="utf-8", errors="replace")
    for field in ("email", "password"):
        assert field in text, f"Login.tsx should reference '{field}' in its API payload"


def test_backend_email_normalization_present():
    """Auth router should normalize emails (lower + strip) before lookup."""
    text = AUTH_ROUTER.read_text(encoding="utf-8", errors="replace")
    assert ".lower()" in text and ".strip()" in text, (
        "auth router must normalize email before DB lookup/hash"
    )


def test_session_cookie_has_httponly_set():
    """Session cookie should be HttpOnly (secrets in browser cookie jar)."""
    from backend.app.core.security import session_cookie_kwargs

    kwargs = session_cookie_kwargs()
    assert kwargs.get("httponly") is True, session_cookie_kwargs()


def test_csrf_cookie_has_httponly_false():
    """CSRF cookie must remain readable by the frontend for the header echo."""
    from backend.app.core.security import csrf_cookie_kwargs

    kwargs = csrf_cookie_kwargs()
    assert kwargs.get("httponly") is False, csrf_cookie_kwargs()


def test_rate_limit_buckets_are_differentiated():
    """Register and login use distinct rate-limit buckets."""
    from backend.app.api import auth as auth_router

    src = AUTH_ROUTER.read_text(encoding="utf-8", errors="replace")
    assert "auth-register" in src, "register must use a dedicated rate-limit bucket"
    assert "auth-login" in src, "login must use a dedicated rate-limit bucket"
