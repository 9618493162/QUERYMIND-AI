"""Authenticated encryption for stored database connection passwords."""

from __future__ import annotations

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken

from app.core.config import settings
from app.core.errors import ApiError


class EncryptionConfigError(Exception):
    """Raised when ENCRYPTION_KEY is missing or unusable."""


_fernet: Fernet | None = None
_fernet_error: str | None = None


def _build_fernet() -> Fernet:
    raw = settings.encryption_key.strip()
    if not raw:
        raise EncryptionConfigError(
            "ENCRYPTION_KEY is not configured. Generate one with: "
            'python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"'
        )
    try:
        # Accept a standard Fernet key, or derive a stable 32-byte key from any
        # high-entropy passphrase (base64 urlsafe of sha256).
        key = raw.encode("utf-8")
        try:
            Fernet(key)
            return Fernet(key)
        except (ValueError, TypeError):
            pass
        derived = base64.urlsafe_b64encode(hashlib.sha256(raw.encode("utf-8")).digest())
        return Fernet(derived)
    except EncryptionConfigError:
        raise
    except Exception as exc:  # pragma: no cover - defensive
        raise EncryptionConfigError(f"ENCRYPTION_KEY is invalid: {exc}") from exc


def get_fernet() -> Fernet:
    global _fernet, _fernet_error
    if _fernet is None:
        try:
            _fernet = _build_fernet()
            _fernet_error = None
        except EncryptionConfigError as exc:
            _fernet_error = str(exc)
            raise
    return _fernet


def encryption_available() -> tuple[bool, str | None]:
    try:
        get_fernet()
        return True, None
    except EncryptionConfigError as exc:
        return False, str(exc)


def encrypt_secret(plaintext: str) -> str:
    try:
        return get_fernet().encrypt(plaintext.encode("utf-8")).decode("ascii")
    except EncryptionConfigError as exc:
        raise ApiError(
            503,
            "encryption_not_configured",
            "Connection passwords cannot be stored because ENCRYPTION_KEY is not configured.",
        ) from exc


def decrypt_secret(ciphertext: str) -> str:
    try:
        return get_fernet().decrypt(ciphertext.encode("ascii")).decode("utf-8")
    except EncryptionConfigError as exc:
        raise ApiError(
            503,
            "encryption_not_configured",
            "Stored credentials cannot be read because ENCRYPTION_KEY is not configured.",
        ) from exc
    except InvalidToken as exc:
        raise ApiError(
            500,
            "credential_decryption_failed",
            "Stored credentials could not be decrypted. The ENCRYPTION_KEY may have changed; "
            "re-enter the connection password.",
        ) from exc


def reset_cache() -> None:
    global _fernet, _fernet_error
    _fernet = None
    _fernet_error = None
