from fastapi import APIRouter,HTTPException,Depends
from pydantic import BaseModel
from services.auth_service import register,login,refresh,update_settings
from middleware.auth import get_current_user
router=APIRouter()
class Reg(BaseModel): email:str; password:str; username:str
class Log(BaseModel): email:str; password:str
class Ref(BaseModel): refresh_token:str
@router.post("/register")
async def do_register(r:Reg):
    res=await register(r.email,r.password,r.username)
    if "error" in res: raise HTTPException(400,detail=res["error"])
    return res
@router.post("/login")
async def do_login(r:Log):
    res=await login(r.email,r.password)
    if "error" in res: raise HTTPException(401,detail=res["error"])
    return res
@router.post("/refresh")
async def do_refresh(r:Ref):
    res=await refresh(r.refresh_token)
    if "error" in res: raise HTTPException(401,detail=res["error"])
    return res
@router.get("/me")
async def me(user=Depends(get_current_user)): return user
@router.patch("/settings")
async def settings(data:dict,user=Depends(get_current_user)): return await update_settings(user["id"],data)
