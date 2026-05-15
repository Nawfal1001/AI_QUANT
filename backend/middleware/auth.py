"""
JWT authentication middleware.
- Requires JWT_SECRET env var (fails loudly if missing or default)
- Provides get_current_user, require_admin, optional_user dependencies
"""
import os
from fastapi import Depends, HTTPException
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
import jwt

from services.logger import log

bearer = HTTPBearer(auto_error=False)
optional_bearer = HTTPBearer(auto_error=False)

JWT_SECRET = os.getenv("JWT_SECRET", "")
JWT_ALGO = "HS256"
JWT_ISSUER = os.getenv("JWT_ISSUER", "tradeai")
JWT_AUDIENCE = os.getenv("JWT_AUDIENCE", "tradeai-clients")

UNSAFE_SECRETS = {"", "tradeai_secret_change_me", "change_me", "secret", "test"}

if JWT_SECRET in UNSAFE_SECRETS or len(JWT_SECRET) < 32:
    log.error(
        "JWT_SECRET is missing or insecure. Set JWT_SECRET in .env to a random 32+ char string. "
        "Generate one: python -c 'import secrets; print(secrets.token_urlsafe(48))'"
    )
    # Don't crash here — let import succeed so commands like `--help` work,
    # but every auth attempt will return 500 below.


def _decode(token: str) -> dict:
    if JWT_SECRET in UNSAFE_SECRETS or len(JWT_SECRET) < 32:
        raise HTTPException(500, "Server misconfigured: JWT_SECRET not set securely")
    try:
        # Accept tokens minted before iss/aud were added — only enforce when the
        # token actually carries those claims — but always require exp.
        return jwt.decode(
            token, JWT_SECRET, algorithms=[JWT_ALGO],
            audience=JWT_AUDIENCE, issuer=JWT_ISSUER,
            options={"require": ["exp", "sub"], "verify_aud": True, "verify_iss": True},
        )
    except jwt.MissingRequiredClaimError:
        # Legacy token without iss/aud — accept once but downgrade verification.
        try:
            return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGO], options={"require": ["exp", "sub"]})
        except jwt.InvalidTokenError as e:
            log.warning(f"Invalid legacy token: {e}")
            raise HTTPException(401, "Invalid token")
    except jwt.ExpiredSignatureError:
        raise HTTPException(401, "Token expired")
    except jwt.InvalidTokenError as e:
        log.warning(f"Invalid token: {e}")
        raise HTTPException(401, "Invalid token")


async def _user_from_payload(payload: dict) -> dict:
    if payload.get("type") != "access":
        raise HTTPException(401, "Invalid token type")
    from database import db
    from bson import ObjectId
    try:
        oid = ObjectId(payload["sub"])
    except Exception:
        raise HTTPException(401, "Invalid token subject")
    user = await db["users"].find_one({"_id": oid})
    if not user:
        raise HTTPException(401, "User not found")
    return {
        "id": str(user["_id"]),
        "email": user["email"],
        "username": user["username"],
        "role": user.get("role", "user"),
        "settings": user.get("settings", {}),
    }


async def get_current_user(creds: HTTPAuthorizationCredentials = Depends(bearer)):
    """Require a valid access token. Returns user dict."""
    if not creds:
        raise HTTPException(401, "Not authenticated")
    payload = _decode(creds.credentials)
    return await _user_from_payload(payload)


async def optional_user(creds: HTTPAuthorizationCredentials = Depends(optional_bearer)):
    """For routes that should work with or without auth (e.g. public market data)."""
    if not creds:
        return None
    try:
        payload = _decode(creds.credentials)
        return await _user_from_payload(payload)
    except HTTPException:
        return None


async def require_admin(user=Depends(get_current_user)):
    """Require admin role."""
    if user.get("role") != "admin":
        raise HTTPException(403, "Admin access required")
    return user


def is_admin(user: dict) -> bool:
    return user and user.get("role") == "admin"


def scope_filter(user: dict, additional: dict = None) -> dict:
    """
    Returns a MongoDB filter that scopes queries to the user, except for admins who see all.
    Usage: docs = await col.find(scope_filter(user)).to_list(50)
    """
    base = {} if is_admin(user) else {"user_id": user["id"]}
    if additional:
        base.update(additional)
    return base
