"""
Symmetric encryption for at-rest broker credentials.

Uses Fernet (AES-128-CBC + HMAC-SHA256) keyed from CREDS_ENCRYPTION_KEY.
The key must be a base64-encoded 32-byte value. Generate one with:
    python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

If CREDS_ENCRYPTION_KEY is not set, derive a key from JWT_SECRET so the system
remains functional in dev environments — log a loud warning so operators
configure a dedicated key in production.
"""
import base64
import hashlib
import os

from services.logger import child

log = child("crypto")

_cipher = None
_key_source = None


def _derive_key() -> bytes:
    explicit = os.getenv("CREDS_ENCRYPTION_KEY", "").strip()
    if explicit:
        try:
            # Validate it's a proper 32-byte base64 key
            raw = base64.urlsafe_b64decode(explicit.encode())
            if len(raw) == 32:
                global _key_source
                _key_source = "CREDS_ENCRYPTION_KEY"
                return explicit.encode()
        except Exception:
            pass
        log.warning("CREDS_ENCRYPTION_KEY is set but not a valid 32-byte base64 key; falling back to JWT_SECRET-derived key")

    jwt_secret = os.getenv("JWT_SECRET", "")
    if not jwt_secret or len(jwt_secret) < 32:
        raise RuntimeError(
            "Neither CREDS_ENCRYPTION_KEY nor a secure JWT_SECRET is configured. "
            "Set CREDS_ENCRYPTION_KEY (generated with Fernet.generate_key()) before "
            "storing broker credentials."
        )
    log.warning("CREDS_ENCRYPTION_KEY not set — deriving credential key from JWT_SECRET. "
                "For production, set CREDS_ENCRYPTION_KEY to a dedicated Fernet key.")
    digest = hashlib.sha256(jwt_secret.encode()).digest()
    globals()["_key_source"] = "JWT_SECRET-derived"
    return base64.urlsafe_b64encode(digest)


def _get_cipher():
    global _cipher
    if _cipher is None:
        from cryptography.fernet import Fernet
        _cipher = Fernet(_derive_key())
    return _cipher


def encrypt(plaintext: str) -> str:
    """Encrypt a string. Returns the Fernet token (urlsafe-base64 string)."""
    if plaintext is None or plaintext == "":
        return ""
    token = _get_cipher().encrypt(plaintext.encode())
    return token.decode()


def decrypt(token: str) -> str:
    """Decrypt a Fernet token. Returns empty string on any failure."""
    if not token:
        return ""
    try:
        return _get_cipher().decrypt(token.encode()).decode()
    except Exception:
        # Try a legacy base64 decode (so credentials saved under the old scheme
        # can still be read until the user rotates them).
        try:
            return base64.b64decode(token.encode()).decode()
        except Exception:
            return ""
