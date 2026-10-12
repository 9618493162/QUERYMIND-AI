"""Application configuration loaded from environment variables."""

from __future__ import annotations

from functools import lru_cache
from typing import Literal
from urllib.parse import parse_qs, urlparse, urlsplit

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_LOOPBACK_HOSTS = {"localhost", "127.0.0.1", "::1", "0.0.0.0"}
_TLS_SSLMODES = {"require", "verify-ca", "verify-full"}


def _is_loopback_origin(origin: str) -> bool:
    host = (urlparse(origin).hostname or "").lower()
    return host in _LOOPBACK_HOSTS


def _database_url_parts(url: str) -> tuple[str, str]:
    """Return (host, sslmode) parsed from a SQLAlchemy database URL."""
    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    mode = (parse_qs(parts.query).get("sslmode") or [""])[0].lower()
    return host, mode


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

    # AI provider ("ollama" or "nvidia")
    ai_provider: str = "ollama"
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "qwen2.5-coder:7b"
    # NVIDIA NIM (OpenAI-compatible chat completions API). The model ID is
    # always taken from NVIDIA_MODEL — no model ID is assumed anywhere.
    nvidia_api_key: str = ""
    nvidia_base_url: str = "https://integrate.api.nvidia.com/v1"
    nvidia_model: str = ""
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

    # Metadata database connection pool. These are PER uvicorn process, so keep
    # ``db_pool_size + db_max_overflow`` below the connection cap of a managed
    # PostgreSQL instance (and below any pooler limit).
    db_pool_size: int = Field(default=10, ge=1)
    db_max_overflow: int = Field(default=10, ge=0)
    db_pool_timeout_seconds: float = Field(default=30.0, gt=0)
    db_pool_recycle_seconds: int = Field(default=1800, ge=0)
    # Require TLS for the metadata database in production. Only disable this for
    # a database that is reachable exclusively on a private network.
    require_db_tls: bool = True

    # Reverse proxies whose ``X-Forwarded-For`` header may be believed (IPs or
    # CIDRs, comma separated). Empty means forwarding headers are ignored.
    trusted_proxy_ips: str = ""

    # Short-lived cache for GET /api/health/ai so repeated probes do not hammer
    # the model server. 0 disables the cache.
    ai_health_cache_seconds: float = Field(default=15.0, ge=0)

    log_level: str = "INFO"

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

    @field_validator("log_level")
    @classmethod
    def _valid_log_level(cls, v: str) -> str:
        level = v.upper().strip()
        if level not in {"CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG"}:
            raise ValueError(
                "LOG_LEVEL must be one of CRITICAL, ERROR, WARNING, INFO, DEBUG"
            )
        return level

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

    @property
    def trusted_proxies(self) -> list[str]:
        """Reverse proxies allowed to set forwarding headers (IPs/CIDRs)."""
        return [p.strip() for p in self.trusted_proxy_ips.split(",") if p.strip()]

    @property
    def max_db_connections(self) -> int:
        """Upper bound of connections a single process can open."""
        return self.db_pool_size + self.db_max_overflow

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
        # The metadata database carries credentials and user data: require TLS
        # unless it is explicitly documented as private-network only.
        if self.require_db_tls:
            host, sslmode = _database_url_parts(self.database_url)
            if host and host not in _LOOPBACK_HOSTS and sslmode not in _TLS_SSLMODES:
                problems.append(
                    "DATABASE_URL must require TLS in production (append ?sslmode=require), "
                    "or set REQUIRE_DB_TLS=false when the database is only reachable on a "
                    "private network."
                )
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
        # A selected provider must be fully configured: an NVIDIA deployment
        # without its credential/model would fail every request at runtime.
        if self.ai_provider.lower().strip() == "nvidia":
            if not self.nvidia_api_key:
                problems.append("NVIDIA_API_KEY must be set when AI_PROVIDER=nvidia.")
            if not self.nvidia_model:
                problems.append("NVIDIA_MODEL must be set when AI_PROVIDER=nvidia.")
        # Cookie + CORS settings that must be safe in production.
        problems.extend(self.validate_production_security())
        return problems


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
