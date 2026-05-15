from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, constr
from typing import Optional

from services.auth_service import register, login, refresh, update_settings
from middleware.auth import get_current_user

router = APIRouter()


class Reg(BaseModel):
    email: constr(strip_whitespace=True, max_length=120)
    password: constr(min_length=8, max_length=72)
    username: constr(strip_whitespace=True, min_length=3, max_length=32)


class Log(BaseModel):
    email: constr(strip_whitespace=True, max_length=120)
    password: constr(min_length=1, max_length=72)


class Ref(BaseModel):
    refresh_token: constr(min_length=10, max_length=4096)


class SettingsUpdate(BaseModel):
    mode: Optional[str] = None
    language: Optional[str] = None
    theme: Optional[str] = None
    notifications_email: Optional[bool] = None
    notifications_telegram: Optional[bool] = None
    default_broker: Optional[str] = None
    default_timeframe: Optional[str] = None
    ui_density: Optional[str] = None


@router.post("/register")
async def do_register(r: Reg):
    res = await register(r.email, r.password, r.username)
    if "error" in res:
        raise HTTPException(400, detail=res["error"])
    return res


@router.post("/login")
async def do_login(r: Log):
    res = await login(r.email, r.password)
    if "error" in res:
        raise HTTPException(401, detail=res["error"])
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
async def settings(data: SettingsUpdate, user=Depends(get_current_user)):
    payload = {k: v for k, v in data.model_dump().items() if v is not None}
    return await update_settings(user["id"], payload)
