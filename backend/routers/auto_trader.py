from fastapi import APIRouter, Depends, HTTPException, Query
from datetime import datetime, timedelta

from middleware.auth import get_current_user, require_admin, scope_filter
from services.auto_trader import (
    get_config, update_config, scan_and_execute, monitor_open,
    start_scheduler, stop_scheduler,
)
from services import risk_engine
from database import db

router = APIRouter()

def _oid(d):
    if d and d.get("_id") is not None:
        d["_id"] = str(d["_id"])
    return d

async def _audit(event, level='info', data=None):
    doc={"ts":datetime.utcnow().isoformat(),"event":event,"level":level,"data":data or {}}
    await db["autotrader_audit_logs"].insert_one(doc)

@router.get("/config")
async def config(user=Depends(get_current_user)):
    return await get_config()

@router.get("/dashboard")
async def dashboard(user=Depends(get_current_user)):
    cfg = await get_config()
    stats_q = scope_filter(user)
    open_q = scope_filter(user, {"status": "open"})
    total = await db["trade_history"].count_documents(stats_q)
    wins = await db["trade_history"].count_documents({**stats_q, "outcome": "WIN"})
    open_cnt = await db["open_trades"].count_documents(open_q)
    last_open = await db["open_trades"].find(open_q).sort("opened_at", -1).limit(10).to_list(10)
    last_hist = await db["trade_history"].find(stats_q).sort("closed_at", -1).limit(10).to_list(10)
    suggestions = await db["bot_strategy_suggestions"].find(scope_filter(user)).sort("created_at", -1).limit(10).to_list(10)
    recent_signals = await db["auto_signals"].find({"signal": {"$regex": "BUY|SELL", "$options": "i"}}).sort("created_at", -1).limit(15).to_list(15)
    now = datetime.utcnow(); interval = int(cfg.get("scan_interval", 300) or 300)
    return {"config": cfg,"schedule": {"enabled": bool(cfg.get("enabled")),"scan_interval_sec": interval,"scan_interval_min": round(interval / 60, 2),"next_scan_estimate": (now + timedelta(seconds=interval)).isoformat(),"signal_source": cfg.get("signal_source", "hybrid"),"auto_signal_limit": cfg.get("auto_signal_limit", 25),"allow_diagnostic_auto_signals": bool(cfg.get("allow_diagnostic_auto_signals", True)),"paper_mode": bool(cfg.get("paper_mode", True))},"stats": {"total_trades": total, "wins": wins, "losses": total - wins, "win_rate": round(wins / max(total, 1) * 100, 1), "open_positions": open_cnt},"open_trades": [_oid(x) for x in last_open],"recent_history": [_oid(x) for x in last_hist],"suggestions": [_oid(x) for x in suggestions],"recent_auto_signals": [_oid(x) for x in recent_signals]}

@router.patch("/config")
async def upd(d: dict, user=Depends(require_admin)):
    try:
        await _audit("config_update_requested", data={"user":user.get("email") or user.get("id"),"patch":d})
        if d.get("enabled") is True:
            if not await risk_engine.is_configured(user["id"]):
                await _audit("config_update_blocked", "warning", {"reason":"Risk limits not configured"})
                raise HTTPException(400, "Risk limits not configured. Set them in Settings first.")
        res=await update_config(d)
        await _audit("config_update_saved", "success", {"config":res})
        return res
    except HTTPException:
        raise
    except Exception as e:
        await _audit("config_update_failed", "error", {"error":str(e)})
        raise HTTPException(400, str(e))

@router.post("/start")
async def start(user=Depends(require_admin)):
    await _audit("scheduler_start_requested", data={"user":user.get("email") or user.get("id")})
    return await start_scheduler()

@router.post("/stop")
async def stop(user=Depends(require_admin)):
    await _audit("scheduler_stop_requested", data={"user":user.get("email") or user.get("id")})
    return await stop_scheduler()

@router.post("/scan-now")
async def scan(user=Depends(require_admin)):
    await _audit("manual_scan_started", data={"user":user.get("email") or user.get("id")})
    try:
        res=await scan_and_execute()
        await _audit("manual_scan_finished", "success", res)
        return res
    except Exception as e:
        await _audit("manual_scan_failed", "error", {"error":str(e)})
        raise HTTPException(400, str(e))

@router.post("/monitor-now")
async def monitor(user=Depends(require_admin)):
    await _audit("monitor_started", data={"user":user.get("email") or user.get("id")})
    try:
        res=await monitor_open()
        await _audit("monitor_finished", "success", res)
        return res
    except Exception as e:
        await _audit("monitor_failed", "error", {"error":str(e)})
        raise HTTPException(400, str(e))

@router.get("/audit-logs")
async def audit_logs(limit:int=Query(100,ge=1,le=500), user=Depends(get_current_user)):
    docs=await db["autotrader_audit_logs"].find({}).sort("ts",-1).limit(limit).to_list(limit)
    return {"logs":[_oid(d) for d in docs]}

@router.get("/open-trades")
async def open_trades(user=Depends(get_current_user)):
    q = scope_filter(user, {"status": "open"})
    trades = await db["open_trades"].find(q).to_list(100)
    for t in trades: t["_id"] = str(t["_id"])
    return {"trades": trades}

@router.get("/trade-history")
async def history(limit: int = Query(50, ge=1, le=500), user=Depends(get_current_user)):
    q = scope_filter(user)
    trades = await db["trade_history"].find(q).sort("closed_at", -1).limit(limit).to_list(limit)
    for t in trades: t["_id"] = str(t["_id"])
    return {"history": trades}

@router.get("/suggestions")
async def suggestions(limit: int = Query(50, ge=1, le=200), user=Depends(get_current_user)):
    docs = await db["bot_strategy_suggestions"].find(scope_filter(user)).sort("created_at", -1).limit(limit).to_list(limit)
    return {"suggestions": [_oid(d) for d in docs], "count": len(docs)}

@router.post("/suggestions/{suggestion_id}/apply")
async def apply_suggestion(suggestion_id: str, user=Depends(require_admin)):
    from bson import ObjectId
    try: oid = ObjectId(suggestion_id)
    except Exception: raise HTTPException(400, "invalid suggestion id")
    sug = await db["bot_strategy_suggestions"].find_one({"_id": oid})
    if not sug: raise HTTPException(404, "suggestion not found")
    bot_cfg = sug.get("bot_config_suggestion") or {}; updates = {}
    if bot_cfg.get("min_confidence") is not None: updates["min_confidence"] = int(bot_cfg["min_confidence"])
    if bot_cfg.get("sizing_pct") is not None: updates["risk_per_trade"] = float(bot_cfg["sizing_pct"])
    if bot_cfg.get("schedule"): updates["timeframe"] = bot_cfg.get("schedule")
    updates["signal_source"] = "auto_signals"; updates["allow_diagnostic_auto_signals"] = True
    await update_config(updates)
    await db["bot_strategy_suggestions"].update_one({"_id": oid}, {"$set": {"status": "applied", "applied_at": datetime.utcnow().isoformat(), "applied_updates": updates}})
    await _audit("suggestion_applied", "success", {"suggestion_id":suggestion_id,"updates":updates})
    return {"status": "applied", "updates": updates, "suggestion": _oid(sug)}

@router.get("/stats")
async def stats(user=Depends(get_current_user)):
    q = scope_filter(user); open_q = scope_filter(user, {"status": "open"})
    total = await db["trade_history"].count_documents(q); wins = await db["trade_history"].count_documents({**q, "outcome": "WIN"}); open_cnt = await db["open_trades"].count_documents(open_q)
    return {"total_trades": total,"wins": wins,"losses": total - wins,"win_rate": round(wins / max(total, 1) * 100, 1),"open_positions": open_cnt}
