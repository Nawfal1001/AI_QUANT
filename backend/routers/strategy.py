from fastapi import APIRouter, Depends
from pydantic import BaseModel
from typing import List

from services.regime_service import detect_regime, detect_global, get_history
from services.strategy_manager import (
    get_strategies, apply_strategy, check_and_switch,
    get_pending, confirm_switch, start_regime_scheduler,
)
from middleware.auth import get_current_user, require_admin

router = APIRouter()


class WL(BaseModel):
    ticker: str
    type: str = "stock"


class RegCheck(BaseModel):
    watchlist: List[WL]
    paper_mode: bool = True


@router.get("/detect/{ticker}")
async def detect(ticker: str, asset_type: str = "stock", user=Depends(get_current_user)):
    return await detect_regime(ticker.upper(), asset_type)


@router.post("/detect-global")
async def dg(req: RegCheck, user=Depends(get_current_user)):
    return await detect_global([w.dict() for w in req.watchlist])


@router.post("/check-and-switch")
async def cs(req: RegCheck, user=Depends(get_current_user)):
    return await check_and_switch([w.dict() for w in req.watchlist], req.paper_mode)


@router.get("/history")
async def hist(ticker: str = None, limit: int = 50, user=Depends(get_current_user)):
    return {"history": await get_history(ticker, limit)}


@router.get("/pending")
async def pending(user=Depends(get_current_user)):
    return {"pending": await get_pending()}


@router.post("/confirm/{pid}")
async def confirm(pid: str, user=Depends(get_current_user)):
    return await confirm_switch(pid)


@router.get("/strategies")
async def strategies(user=Depends(get_current_user)):
    return {"strategies": await get_strategies()}


@router.post("/strategies/{sid}/apply")
async def apply(sid: str, user=Depends(get_current_user)):
    return await apply_strategy(sid)


# Scheduler control is admin-only — affects all users
@router.post("/scheduler/start")
async def start_sched(req: RegCheck, user=Depends(require_admin)):
    return await start_regime_scheduler([w.dict() for w in req.watchlist], req.paper_mode)
