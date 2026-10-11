"""Application configuration loaded from environment variables."""

from __future__ import annotations

from functools import lru_cache
from typing import Literal
from urllib.parse import urlparse

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_LOOPBACK_HOSTS = {"localhost", "127.0.0.1", "::1", "0.0.0.0"}


def _is_loopback_origin(origin: str) -> bool:
    host = (urlparse(origin).hostname or "").lower()
    return host in _LOOPBACK_HOSTS


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_env: Literal["development", "test", "production"] = "development"
    app_secret_key: str = Field(default="", min_length=0)

    # Application metadata database
    database_url: str = (
        "postgresql+psycopg://app_user:app_password_change_me@localhost:5432/querymind"
    )

    # AI provider
    ai_provider: str = "ollama"
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "qwen2.5-coder:7b"
    ai_timeout_seconds: float = 60.0
    ai_max_retries: int = 2

    # Credential encryption
    encryption_key: str = ""

    # Frontend
    frontend_origin: str = "http://localhost:5173"

    # Query limits
    query_timeout_seconds: int = 15
    max_query_rows: int = 1000
    max_result_bytes: int = 5_000_000

    # Network policy
    allow_private_db_hosts: bool = True
    db_destination_allowlist: str = ""

    # Rate limits (per minute)
    auth_rate_limit_per_minute: int = 10
    query_rate_limit_per_minute: int = 30

    # Cookie names (public)
    session_cookie: str = "querymind_session"
    csrf_cookie: str = "querymind_csrf"
    csrf_header: str = "x-csrf-token"

    # Cookie hardening. When `cookie_secure` is unset the Secure flag follows
    # `app_env`: it is mandatory in production and off in local development.
    cookie_secure: bool | None = None
    cookie_samesite: Literal["lax", "strict", "none"] = "lax"

    @field_validator("app_secret_key")
    @classmethod
    def _warn_default_secret(cls, v: str) -> str:
        return v

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

    @property
    def allowlist_hosts(self) -> list[str]:
        return [h.strip() for h in self.db_destination_allowlist.split(",") if h.strip()]

    @property
    def cors_origins(self) -> list[str]:
        """Explicit CORS allowlist parsed from FRONTEND_ORIGIN (comma-separated).

        CORS is never configured as a wildcard while credentials (cookies) are
        enabled; a trailing slash is stripped so ``https://app.example.com/``
        and ``https://app.example.com`` are treated as the same origin.
        """
        return [o.strip().rstrip("/") for o in self.frontend_origin.split(",") if o.strip()]

    @property
    def cookies_are_secure(self) -> bool:
        """Effective Secure flag for the session and CSRF cookies."""
        return self.cookie_secure if self.cookie_secure is not None else self.is_production

    def validate_production_security(self) -> list[str]:
        """Fatal problems with production cookie/CORS settings (empty when OK).

        These are the settings that silently weaken security in production: an
        insecure or wildcard CORS origin, a non-HTTPS origin (the browser would
        drop the Secure cookies), or cookies that were explicitly marked
        non-Secure. Non-production environments are not gated here.
        """
        if not self.is_production:
            return []
        problems: list[str] = []
        origins = self.cors_origins
        if not origins:
            problems.append("FRONTEND_ORIGIN must name at least one explicit origin in production.")
        for origin in origins:
            if origin == "*":
                problems.append(
                    "FRONTEND_ORIGIN must not be '*' while credential cookies are enabled."
                )
            elif not origin.startswith("https://"):
                problems.append(
                    f"FRONTEND_ORIGIN must use https:// in production (got '{origin}')."
                )
            elif _is_loopback_origin(origin):
                problems.append(
                    f"FRONTEND_ORIGIN must not point at localhost in production (got '{origin}')."
                )
        if not self.cookies_are_secure:
            problems.append(
                "Session and CSRF cookies must be Secure in production; COOKIE_SECURE cannot be false."
            )
        if self.cookie_samesite == "none" and not self.cookies_are_secure:
            problems.append("COOKIE_SAMESITE=none requires Secure cookies.")
        return problems

    def validate_for_runtime(self) -> list[str]:
        """Return a list of fatal configuration problems (empty when OK).

        In production this is treated as a hard gate: the application must either
        refuse to start or run with explicitly safe defaults.
        """
        problems: list[str] = []
        if not self.app_secret_key or self.app_secret_key.startswith("replace-"):
            if self.is_production:
                problems.append("APP_SECRET_KEY must be set to a strong random value in production.")
            elif not self.app_secret_key:
                problems.append("APP_SECRET_KEY is not set.")
        if not self.encryption_key:
            problems.append(
                "ENCRYPTION_KEY is not set. Generate one with: "
                'python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"'
            )
        # Cookie + CORS settings that must be safe in production.
        problems.extend(self.validate_production_security())
        return problems


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
