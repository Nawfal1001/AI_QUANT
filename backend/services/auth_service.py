"""
Auth service: register / login / refresh / user lookup.
- Reads JWT_SECRET from env dynamically.
- Logs all auth events.
"""
import os
from datetime import datetime, timedelta

import bcrypt
import jwt

from database import db
from services.logger import child

log = child("auth")
users = db["users"]

JWT_ALGO = "HS256"
ACCESS_TTL_MIN = int(os.getenv("ACCESS_TTL_MIN", str(60 * 24)))      # 1 day
REFRESH_TTL_MIN = int(os.getenv("REFRESH_TTL_MIN", str(60 * 24 * 30)))  # 30 days


def _jwt_secret() -> str:
    return os.getenv("JWT_SECRET", "")


def hash_pw(p: str) -> str:
    return bcrypt.hashpw(p.encode(), bcrypt.gensalt()).decode()


def verify_pw(p: str, h: str) -> bool:
    try:
        return bcrypt.checkpw(p.encode(), h.encode())
    except Exception as e:
        log.warning(f"verify_pw error: {e}")
        return False


def make_token(uid: str, kind: str = "access") -> str:
    secret = _jwt_secret()
    if not secret or len(secret) < 32:
        raise RuntimeError("JWT_SECRET not configured. Set it in .env (32+ random chars).")
    ttl = ACCESS_TTL_MIN if kind == "access" else REFRESH_TTL_MIN
    payload = {"sub": uid, "type": kind, "exp": datetime.utcnow() + timedelta(minutes=ttl)}
    return jwt.encode(payload, secret, algorithm=JWT_ALGO)


async def register(email: str, password: str, username: str):
    email_l = (email or "").lower().strip()
    username_s = (username or "").strip()
    if not email_l or "@" not in email_l:
        return {"error": "Invalid email"}
    if not username_s or len(username_s) < 3:
        return {"error": "Username must be 3+ chars"}
    if len(password or "") < 8:
        return {"error": "Password must be 8+ chars"}
    if await users.find_one({"email": email_l}):
        return {"error": "Email already registered"}
    if await users.find_one({"username": username_s}):
        return {"error": "Username taken"}

    first_user = (await users.count_documents({})) == 0
    role = "admin" if first_user else "user"

    doc = {
        "email": email_l,
        "username": username_s,
        "password": hash_pw(password),
        "role": role,
        "created_at": datetime.utcnow().isoformat(),
        "settings": {"mode": "paper", "language": "en"},
    }
    r = await users.insert_one(doc)
    uid = str(r.inserted_id)
    log.info(f"registered user {username_s} ({uid}) role={role}")
    return {
        "access_token": make_token(uid),
        "refresh_token": make_token(uid, "refresh"),
        "user": {"id": uid, "email": email_l, "username": username_s, "role": role, "settings": doc["settings"]},
    }


async def login(email: str, password: str):
    email_l = (email or "").lower().strip()
    u = await users.find_one({"email": email_l})
    if not u or not verify_pw(password, u["password"]):
        log.info(f"failed login for {email_l}")
        return {"error": "Invalid credentials"}
    uid = str(u["_id"])
    await users.update_one({"_id": u["_id"]}, {"$set": {"last_login": datetime.utcnow().isoformat()}})
    log.info(f"login: {u['username']} ({uid})")
    return {
        "access_token": make_token(uid),
        "refresh_token": make_token(uid, "refresh"),
        "user": {
            "id": uid,
            "email": u["email"],
            "username": u["username"],
            "role": u.get("role", "user"),
            "settings": u.get("settings", {}),
        },
    }


async def refresh(token: str):
    secret = _jwt_secret()
    if not secret or len(secret) < 32:
        return {"error": "Server misconfigured"}
    try:
        p = jwt.decode(token, secret, algorithms=[JWT_ALGO])
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
    return {
        "id": str(u["_id"]),
        "email": u["email"],
        "username": u["username"],
        "role": u.get("role", "user"),
        "settings": u.get("settings", {}),
    }


async def update_settings(uid: str, settings: dict):
    from bson import ObjectId
    try:
        await users.update_one({"_id": ObjectId(uid)}, {"$set": {"settings": settings}})
        return {"status": "updated"}
    except Exception as e:
        log.exception(f"update_settings failed: {e}")
        return {"error": str(e)}
