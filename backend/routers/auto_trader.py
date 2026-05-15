from fastapi import APIRouter, Depends, HTTPException

from middleware.auth import get_current_user, require_admin, scope_filter
from services.auto_trader import (
    get_config, update_config, scan_and_execute, monitor_open,
    start_scheduler, stop_scheduler,
)
from services import risk_engine
from database import db

router = APIRouter()


@router.get("/config")
async def config(user=Depends(get_current_user)):
    return await get_config()


@router.patch("/config")
async def upd(d: dict, user=Depends(get_current_user)):
    # If user tries to enable, require risk limits to be configured first
    if d.get("enabled") is True:
        if not await risk_engine.is_configured(user["id"]):
            raise HTTPException(400, "Risk limits not configured. Set them in Settings first.")
    return await update_config(d)


# Admin-only: scheduler thread is global
@router.post("/start")
async def start(user=Depends(require_admin)):
    return await start_scheduler()


@router.post("/stop")
async def stop(user=Depends(require_admin)):
    return await stop_scheduler()


@router.post("/scan-now")
async def scan(user=Depends(get_current_user)):
    return await scan_and_execute()


@router.post("/monitor-now")
async def monitor(user=Depends(get_current_user)):
    return await monitor_open()


@router.get("/open-trades")
async def open_trades(user=Depends(get_current_user)):
    q = scope_filter(user, {"status": "open"})
    trades = await db["open_trades"].find(q).to_list(100)
    for t in trades:
        t["_id"] = str(t["_id"])
    return {"trades": trades}


@router.get("/trade-history")
async def history(limit: int = 50, user=Depends(get_current_user)):
    q = scope_filter(user)
    trades = await db["trade_history"].find(q).sort("closed_at", -1).limit(limit).to_list(limit)
    for t in trades:
        t["_id"] = str(t["_id"])
    return {"history": trades}


@router.get("/stats")
async def stats(user=Depends(get_current_user)):
    q = scope_filter(user)
    open_q = scope_filter(user, {"status": "open"})
    total = await db["trade_history"].count_documents(q)
    wins = await db["trade_history"].count_documents({**q, "outcome": "WIN"})
    open_cnt = await db["open_trades"].count_documents(open_q)
    return {
        "total_trades": total,
        "wins": wins,
        "losses": total - wins,
        "win_rate": round(wins / max(total, 1) * 100, 1),
        "open_positions": open_cnt,
    }
