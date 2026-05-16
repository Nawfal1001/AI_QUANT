"""
Auth service: register / login / refresh / user lookup.
- Reads JWT_SECRET from env dynamically.
- Supports configured admin email allowlist.
- Logs all auth events.
"""
import os
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt

from database import db
from services.logger import child

log = child("auth")
users = db["users"]

JWT_ALGO = "HS256"
JWT_ISSUER = os.getenv("JWT_ISSUER", "tradeai")
JWT_AUDIENCE = os.getenv("JWT_AUDIENCE", "tradeai-clients")
ACCESS_TTL_MIN = int(os.getenv("ACCESS_TTL_MIN", str(60 * 24)))
REFRESH_TTL_MIN = int(os.getenv("REFRESH_TTL_MIN", str(60 * 24 * 30)))
BCRYPT_MAX_BYTES = 72


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _jwt_secret() -> str:
    return os.getenv("JWT_SECRET", "")


def _admin_emails() -> set:
    raw = os.getenv("ADMIN_EMAILS") or os.getenv("ADMIN_EMAIL") or "nawfal1001@gmail.com"
    return {e.strip().lower() for e in raw.split(",") if e.strip()}


def _is_configured_admin(email: str) -> bool:
    return (email or "").lower().strip() in _admin_emails()


def _public_user(u: dict) -> dict:
    email = (u.get("email") or "").lower().strip()
    role = "admin" if _is_configured_admin(email) else u.get("role", "user")
    return {
        "id": str(u["_id"]),
        "email": email,
        "username": u.get("username", email.split("@")[0]),
        "role": role,
        "settings": u.get("settings", {}),
    }


def hash_pw(p: str) -> str:
    if len(p.encode()) > BCRYPT_MAX_BYTES:
        raise ValueError(f"Password too long (max {BCRYPT_MAX_BYTES} bytes)")
    return bcrypt.hashpw(p.encode(), bcrypt.gensalt()).decode()


def verify_pw(p: str, h: str) -> bool:
    try:
        if len(p.encode()) > BCRYPT_MAX_BYTES:
            return False
        return bcrypt.checkpw(p.encode(), h.encode())
    except Exception as e:
        log.warning(f"verify_pw error: {e}")
        return False


def make_token(uid: str, kind: str = "access") -> str:
    secret = _jwt_secret()
    if not secret or len(secret) < 32:
        raise RuntimeError("JWT_SECRET not configured. Set it in .env (32+ random chars).")
    ttl = ACCESS_TTL_MIN if kind == "access" else REFRESH_TTL_MIN
    now = _utc_now()
    payload = {"sub": uid, "type": kind, "iss": JWT_ISSUER, "aud": JWT_AUDIENCE, "iat": now, "nbf": now, "exp": now + timedelta(minutes=ttl)}
    return jwt.encode(payload, secret, algorithm=JWT_ALGO)


async def register(email: str, password: str, username: str):
    email_l = (email or "").lower().strip()
    username_s = (username or "").strip()
    if not email_l or "@" not in email_l:
        return {"error": "Invalid email"}
    if not username_s or len(username_s) < 3:
        return {"error": "Username must be 3+ chars"}
    if len(username_s) > 32:
        return {"error": "Username too long"}
    if len(password or "") < 8:
        return {"error": "Password must be 8+ chars"}
    if len((password or "").encode()) > BCRYPT_MAX_BYTES:
        return {"error": f"Password too long (max {BCRYPT_MAX_BYTES} bytes)"}

    if await users.find_one({"email": email_l}) or await users.find_one({"username": username_s}):
        log.info(f"register collision for email={email_l} username={username_s}")
        return {"error": "Registration failed"}

    allow_bootstrap = os.getenv("ALLOW_ADMIN_BOOTSTRAP", "false").lower() == "true"
    role = "admin" if _is_configured_admin(email_l) else "user"
    if role != "admin" and allow_bootstrap:
        claim = await db["admin_bootstrap"].find_one_and_update(
            {"_id": "claim"},
            {"$setOnInsert": {"claimed": True, "at": _utc_now().isoformat()}},
            upsert=True,
            return_document=False,
        )
        if claim is None:
            role = "admin"

    doc = {"email": email_l, "username": username_s, "password": hash_pw(password), "role": role, "created_at": _utc_now().isoformat(), "settings": {"mode": "paper", "language": "en"}}
    try:
        r = await users.insert_one(doc)
    except Exception as e:
        log.warning(f"register insert failed: {e}")
        return {"error": "Registration failed"}
    uid = str(r.inserted_id)
    log.info(f"registered user uid={uid} role={role}")
    return {"access_token": make_token(uid), "refresh_token": make_token(uid, "refresh"), "user": {"id": uid, "email": email_l, "username": username_s, "role": role, "settings": doc["settings"]}}


async def login(email: str, password: str):
    email_l = (email or "").lower().strip()
    u = await users.find_one({"email": email_l})
    if not u or not verify_pw(password, u["password"]):
        log.info("failed login")
        return {"error": "Invalid credentials"}
    if _is_configured_admin(email_l) and u.get("role") != "admin":
        await users.update_one({"_id": u["_id"]}, {"$set": {"role": "admin", "last_login": _utc_now().isoformat()}})
        u["role"] = "admin"
    else:
        await users.update_one({"_id": u["_id"]}, {"$set": {"last_login": _utc_now().isoformat()}})
    uid = str(u["_id"])
    log.info(f"login: user_id={uid}")
    return {"access_token": make_token(uid), "refresh_token": make_token(uid, "refresh"), "user": _public_user(u)}


async def refresh(token: str):
    secret = _jwt_secret()
    if not secret or len(secret) < 32:
        return {"error": "Server misconfigured"}
    try:
        try:
            p = jwt.decode(token, secret, algorithms=[JWT_ALGO], audience=JWT_AUDIENCE, issuer=JWT_ISSUER, options={"require": ["exp", "sub", "type"]})
        except jwt.MissingRequiredClaimError:
            p = jwt.decode(token, secret, algorithms=[JWT_ALGO], options={"require": ["exp", "sub"]})
        if p.get("type") != "refresh":
            return {"error": "Wrong token type"}
        return {"access_token": make_token(p["sub"])}
    except jwt.ExpiredSignatureError:
        return {"error": "Refresh token expired"}
    except jwt.InvalidTokenError as e:
        log.warning(f"refresh token invalid: {e}")
        return {"error": "Invalid refresh token"}


async def get_user(uid: str):
    from bson import ObjectId
    try:
        u = await users.find_one({"_id": ObjectId(uid)})
    except Exception:
        return None
    if not u:
        return None
    if _is_configured_admin(u.get("email")) and u.get("role") != "admin":
        await users.update_one({"_id": u["_id"]}, {"$set": {"role": "admin"}})
        u["role"] = "admin"
    return _public_user(u)


_ALLOWED_SETTINGS_KEYS = {"mode", "language", "theme", "notifications_email", "notifications_telegram", "default_broker", "default_timeframe", "ui_density"}


async def update_settings(uid: str, settings: dict):
    from bson import ObjectId
    if not isinstance(settings, dict):
        return {"error": "settings must be an object"}
    cleaned = {}
    for k, v in settings.items():
        if k not in _ALLOWED_SETTINGS_KEYS:
            continue
        if isinstance(v, (str, int, float, bool)) or v is None:
            if isinstance(v, str) and len(v) > 200:
                return {"error": f"{k} too long"}
            cleaned[k] = v
    try:
        update = {f"settings.{k}": v for k, v in cleaned.items()}
        if update:
            await users.update_one({"_id": ObjectId(uid)}, {"$set": update})
        return {"status": "updated", "settings": cleaned}
    except Exception as e:
        log.exception(f"update_settings failed: {e}")
        return {"error": "Update failed"}
