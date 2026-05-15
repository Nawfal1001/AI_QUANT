"""Credential encryption helpers.

New broker credentials are encrypted with Fernet when CREDENTIALS_ENCRYPTION_KEY is set.
Legacy Base64-obscured values remain readable for backward compatibility.
"""
import base64
import os
from typing import Optional

from cryptography.fernet import Fernet, InvalidToken

PREFIX = "fernet:"


def _get_fernet() -> Optional[Fernet]:
    key = os.getenv("CREDENTIALS_ENCRYPTION_KEY", "").strip()
    if not key:
        return None
    try:
        return Fernet(key.encode())
    except Exception:
        return None


def encryption_available() -> bool:
    return _get_fernet() is not None


def encrypt_secret(value: str) -> str:
    """Encrypt a secret if configured; otherwise fall back to legacy Base64."""
    if not value:
        return ""
    fernet = _get_fernet()
    if fernet:
        return PREFIX + fernet.encrypt(value.encode()).decode()
    return base64.b64encode(value.encode()).decode()


def decrypt_secret(value: str) -> str:
    """Decrypt Fernet values or decode legacy Base64 values."""
    if not value:
        return ""
    if value.startswith(PREFIX):
        fernet = _get_fernet()
        if not fernet:
            return ""
        try:
            return fernet.decrypt(value[len(PREFIX):].encode()).decode()
        except InvalidToken:
            return ""
    try:
        return base64.b64decode(value.encode()).decode()
    except Exception:
        return ""


def mask_secret(value: str) -> str:
    if not value or len(value) < 6:
        return "****"
    return value[:3] + "****" + value[-3:]
