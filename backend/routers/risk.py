"""Risk limits & kill switch router."""
from fastapi import APIRouter, Depends, HTTPException
from middleware.auth import get_current_user
from services import risk_engine

router = APIRouter()


@router.get("/status")
async def status(user=Depends(get_current_user)):
    return await risk_engine.get_status(user["id"])


@router.get("/limits")
async def get_limits(user=Depends(get_current_user)):
    lim = await risk_engine.get_limits(user["id"])
    if not lim:
        return {"configured": False, "limits": None}
    lim.pop("_id", None)
    return {"configured": True, "limits": lim}


@router.post("/limits")
async def set_limits(payload: dict, user=Depends(get_current_user)):
    res = await risk_engine.set_limits(user["id"], payload)
    if "error" in res:
        raise HTTPException(400, res["error"])
    return res


@router.post("/kill-switch")
async def kill(payload: dict, user=Depends(get_current_user)):
    enabled = bool(payload.get("enabled", True))
    return await risk_engine.set_kill_switch(user["id"], enabled)


@router.post("/check")
async def check(payload: dict, user=Depends(get_current_user)):
    """Manually test an order against risk limits without placing it."""
    size = float(payload.get("position_size_usd", 0))
    ticker = payload.get("ticker", "")
    return await risk_engine.check_order(user["id"], size, ticker)
