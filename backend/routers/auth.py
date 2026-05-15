from fastapi import APIRouter, HTTPException, Depends, Request
from pydantic import BaseModel

from services.auth_service import register, login, refresh, update_settings
from services.rate_limit import check_rate_limit, reset_rate_limit
from middleware.auth import get_current_user

router = APIRouter()


class Reg(BaseModel):
    email: str
    password: str
    username: str


class Log(BaseModel):
    email: str
    password: str


class Ref(BaseModel):
    refresh_token: str


def _client_key(request: Request, email: str) -> str:
    forwarded = request.headers.get("x-forwarded-for", "")
    ip = forwarded.split(",")[0].strip() or (request.client.host if request.client else "unknown")
    return f"login:{ip}:{(email or '').lower().strip()}"


@router.post("/register")
async def do_register(r: Reg):
    res = await register(r.email, r.password, r.username)
    if "error" in res:
        raise HTTPException(400, detail=res["error"])
    return res


@router.post("/login")
async def do_login(r: Log, request: Request):
    key = _client_key(request, r.email)
    if not check_rate_limit(key, limit=5, window_sec=300):
        raise HTTPException(429, detail="Too many login attempts. Try again later.")
    res = await login(r.email, r.password)
    if "error" in res:
        raise HTTPException(401, detail=res["error"])
    reset_rate_limit(key)
    return res


@router.post("/refresh")
async def do_refresh(r: Ref):
    res = await refresh(r.refresh_token)
    if "error" in res:
        raise HTTPException(401, detail=res["error"])
    return res


@router.get("/me")
async def me(user=Depends(get_current_user)):
    return user


@router.patch("/settings")
async def settings(data: dict, user=Depends(get_current_user)):
    return await update_settings(user["id"], data)
