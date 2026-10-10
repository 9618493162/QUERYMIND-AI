"""Application configuration loaded from environment variables."""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


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

    def validate_for_runtime(self) -> list[str]:
        """Return a list of fatal configuration problems (empty when OK)."""
        problems: list[str] = []
        if not self.app_secret_key or self.app_secret_key.startswith("replace-"):
            if self.is_production:
                problems.append("APP_SECRET_KEY must be set to a strong random value in production.")
        if not self.encryption_key:
            problems.append(
                "ENCRYPTION_KEY is not set. Generate one with: "
                'python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"'
            )
        if self.is_production and not self.allow_private_db_hosts and not self.frontend_origin.startswith("https://"):
            problems.append("FRONTEND_ORIGIN must use https:// in production.")
        return problems


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
