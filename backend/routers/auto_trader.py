from fastapi import APIRouter, Depends, HTTPException, Query
from datetime import datetime, timedelta

from middleware.auth import get_current_user, require_admin, scope_filter
from services.auto_trader import (
    get_config, update_config, scan_and_execute, monitor_open,
    start_scheduler, stop_scheduler,
)
from services import risk_engine
from services import ttl_cache
from database import db

router = APIRouter()

def _oid(d):
    if d and d.get("_id") is not None:
        d["_id"] = str(d["_id"])
    return d

async def _audit(event, level='info', data=None):
    doc={"ts":datetime.utcnow().isoformat(),"event":event,"level":level,"data":data or {}}
    await db["autotrader_audit_logs"].insert_one(doc)

def _f(v, default=0.0):
    try: return float(v)
    except Exception: return default

async def _live_price(ticker, atype='stock'):
    from services import data_freshness
    cached = data_freshness.get_price(ticker)
    if cached and cached.get('price'):
        return float(cached.get('price')), cached.get('age_sec'), cached.get('ts') or cached.get('timestamp'), 'cache'
    try:
        from services.backtest_engine import fetch_history
        end_dt=datetime.utcnow(); start_dt=end_dt-timedelta(days=2)
        df=await fetch_history(ticker, atype, start_dt.strftime('%Y-%m-%d'), end_dt.strftime('%Y-%m-%d'), '1h')
        if df is not None and len(df):
            return float(df['close'].iloc[-1]), None, end_dt.isoformat(), 'history_fallback'
    except Exception:
        pass
    return None, None, None, 'unavailable'

def _enrich_trade(t, live_price, price_age_sec=None, price_ts=None, price_source='unavailable'):
    entry=_f(t.get('entry_price')); qty=_f(t.get('quantity') or t.get('qty')); sl=_f(t.get('sl')); tp=_f(t.get('tp')); sig=str(t.get('signal','BUY')).upper(); is_buy='BUY' in sig or sig == 'LONG'
    live=_f(live_price) if live_price is not None else None
    out=_oid(dict(t)); out.update({'live_price': live, 'price_age_sec': price_age_sec, 'price_timestamp': price_ts, 'price_source': price_source, 'broker_synced': False, 'broker_status': 'app_managed'})
    if live is None or entry <= 0:
        out.update({'pnl_pct': None, 'pnl_usd': None, 'distance_to_sl_pct': None, 'distance_to_tp_pct': None, 'should_close_now': False, 'close_trigger': None, 'monitor_status': 'no_live_price'})
        return out
    pnl_pct=((live-entry)/entry*100) if is_buy else ((entry-live)/entry*100)
    pnl_usd=(live-entry)*qty if is_buy else (entry-live)*qty
    hit_sl=(live<=sl) if is_buy else (live>=sl)
    hit_tp=(live>=tp) if is_buy else (live<=tp)
    dist_sl=((live-sl)/live*100) if is_buy and live else ((sl-live)/live*100 if live else None)
    dist_tp=((tp-live)/live*100) if is_buy and live else ((live-tp)/live*100 if live else None)
    close_trigger='TP' if hit_tp else ('SL' if hit_sl else None)
    nearest='TP' if dist_tp is not None and dist_sl is not None and dist_tp < dist_sl else 'SL'
    status='will_close_now' if close_trigger else ('near_tp' if nearest=='TP' and dist_tp is not None and dist_tp <= 0.5 else ('near_sl' if nearest=='SL' and dist_sl is not None and dist_sl <= 0.5 else 'open'))
    out.update({'pnl_pct': round(pnl_pct,3), 'pnl_usd': round(pnl_usd,4), 'distance_to_sl_pct': round(dist_sl,3) if dist_sl is not None else None, 'distance_to_tp_pct': round(dist_tp,3) if dist_tp is not None else None, 'should_close_now': bool(close_trigger), 'close_trigger': close_trigger, 'next_close_condition': f"TP at {tp} / SL at {sl}", 'monitor_status': status})
    return out

@router.get("/config")
async def config(user=Depends(get_current_user)):
    return await get_config()

async def _open_trades_live_payload(user):
    q = scope_filter(user, {"status": "open"})
    trades = await db["open_trades"].find(q).sort("opened_at", -1).to_list(100)
    enriched=[]
    for t in trades:
        price, age, ts, src = await _live_price(t.get('ticker'), t.get('asset_type','stock'))
        enriched.append(_enrich_trade(t, price, age, ts, src))
    return {"trades": enriched, "count": len(enriched), "updated_at": datetime.utcnow().isoformat(), "cache_ttl_sec": 5}

@router.get("/open-trades/live")
async def open_trades_live(user=Depends(get_current_user)):
    key=ttl_cache.make_key('autotrader_live', user.get('id') or user.get('email'))
    return await ttl_cache.cached(key, 5, lambda: _open_trades_live_payload(user))

async def _dashboard_payload(user):
    cfg = await get_config()
    stats_q = scope_filter(user)
    open_q = scope_filter(user, {"status": "open"})
    total = await db["trade_history"].count_documents(stats_q)
    wins = await db["trade_history"].count_documents({**stats_q, "outcome": "WIN"})
    open_cnt = await db["open_trades"].count_documents(open_q)
    last_open = await db["open_trades"].find(open_q).sort("opened_at", -1).limit(10).to_list(10)
    live_open=[]
    for t in last_open:
        price, age, ts, src = await _live_price(t.get('ticker'), t.get('asset_type','stock'))
        live_open.append(_enrich_trade(t, price, age, ts, src))
    last_hist = await db["trade_history"].find(stats_q).sort("closed_at", -1).limit(10).to_list(10)
    suggestions = await db["bot_strategy_suggestions"].find(scope_filter(user)).sort("created_at", -1).limit(10).to_list(10)
    recent_signals = await db["auto_signals"].find({}).sort("created_at", -1).limit(15).to_list(15)
    now = datetime.utcnow(); interval = int(cfg.get("scan_interval", 300) or 300)
    return {"config": cfg,"schedule": {"enabled": bool(cfg.get("enabled")),"scan_interval_sec": interval,"scan_interval_min": round(interval / 60, 2),"next_scan_estimate": (now + timedelta(seconds=interval)).isoformat(),"signal_source": cfg.get("signal_source", "hybrid"),"auto_signal_limit": cfg.get("auto_signal_limit", 25),"allow_diagnostic_auto_signals": bool(cfg.get("allow_diagnostic_auto_signals", True)),"paper_mode": bool(cfg.get("paper_mode", True))},"stats": {"total_trades": total, "wins": wins, "losses": total - wins, "win_rate": round(wins / max(total, 1) * 100, 1), "open_positions": open_cnt},"open_trades": live_open,"recent_history": [_oid(x) for x in last_hist],"suggestions": [_oid(x) for x in suggestions],"recent_auto_signals": [_oid(x) for x in recent_signals],"cache_ttl_sec":5}

@router.get("/dashboard")
async def dashboard(user=Depends(get_current_user)):
    key=ttl_cache.make_key('autotrader_dashboard', user.get('id') or user.get('email'))
    return await ttl_cache.cached(key, 5, lambda: _dashboard_payload(user))

@router.patch("/config")
async def upd(d: dict, user=Depends(require_admin)):
    try:
        await _audit("config_update_requested", data={"user":user.get("email") or user.get("id"),"patch":d})
        if d.get("enabled") is True:
            if not await risk_engine.is_configured(user["id"]):
                await _audit("config_update_blocked", "warning", {"reason":"Risk limits not configured"})
                raise HTTPException(400, "Risk limits not configured. Set them in Settings first.")
        res=await update_config(d)
        ttl_cache.clear('autotrader_dashboard'); ttl_cache.clear('autotrader_live')
        await _audit("config_update_saved", "success", {"config":res})
        return res
    except HTTPException:
        raise
    except Exception as e:
        await _audit("config_update_failed", "error", {"error":str(e)})
        raise HTTPException(400, str(e))

@router.post("/start")
async def start(user=Depends(require_admin)):
    ttl_cache.clear('autotrader_dashboard')
    await _audit("scheduler_start_requested", data={"user":user.get("email") or user.get("id")})
    return await start_scheduler()

@router.post("/stop")
async def stop(user=Depends(require_admin)):
    ttl_cache.clear('autotrader_dashboard')
    await _audit("scheduler_stop_requested", data={"user":user.get("email") or user.get("id")})
    return await stop_scheduler()

@router.post("/scan-now")
async def scan(user=Depends(require_admin)):
    await _audit("manual_scan_started", data={"user":user.get("email") or user.get("id")})
    try:
        res=await scan_and_execute()
        ttl_cache.clear('autotrader_dashboard'); ttl_cache.clear('autotrader_live'); ttl_cache.clear('trade_history')
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
        ttl_cache.clear('autotrader_dashboard'); ttl_cache.clear('autotrader_live'); ttl_cache.clear('trade_history')
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
    key=ttl_cache.make_key('trade_history', user.get('id') or user.get('email'), limit)
    async def build():
        q = scope_filter(user)
        trades = await db["trade_history"].find(q).sort("closed_at", -1).limit(limit).to_list(limit)
        for t in trades: t["_id"] = str(t["_id"])
        return {"history": trades, "cache_ttl_sec": 10}
    return await ttl_cache.cached(key, 10, build)

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
    ttl_cache.clear('autotrader_dashboard')
    await db["bot_strategy_suggestions"].update_one({"_id": oid}, {"$set": {"status": "applied", "applied_at": datetime.utcnow().isoformat(), "applied_updates": updates}})
    await _audit("suggestion_applied", "success", {"suggestion_id":suggestion_id,"updates":updates})
    return {"status": "applied", "updates": updates, "suggestion": _oid(sug)}

@router.get("/stats")
async def stats(user=Depends(get_current_user)):
    q = scope_filter(user); open_q = scope_filter(user, {"status": "open"})
    total = await db["trade_history"].count_documents(q); wins = await db["trade_history"].count_documents({**q, "outcome": "WIN"}); open_cnt = await db["open_trades"].count_documents(open_q)
    return {"total_trades": total,"wins": wins,"losses": total - wins,"win_rate": round(wins / max(total, 1) * 100, 1),"open_positions": open_cnt}
