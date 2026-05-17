"""
TradeAI Auto-Trader v4.5
Uses Auto Universe signals, including high-confidence diagnostic rows when needed, with strict execution gates.
"""
import asyncio, os
from datetime import datetime, timedelta
from database import db
from services.signal_service import generate_signal
from services.position_sizing import optimal_position
from services.advanced_indicators import optimal_trailing_stop
from services.trade_optimizer import run_optimization
from services.logger import child as _child_log
_log = _child_log('auto_trader')
try:
    from services.activity_log import log_event
except Exception:
    log_event = None
cfg_col=db["autotrader_config"]; trades_col=db["open_trades"]; hist_col=db["trade_history"]; rl_ep_col=db["rl_episodes"]
DEFAULT={"enabled":False,"paper_mode":True,"min_confidence":70,"max_open":5,"risk_per_trade":2.0,"capital":10000,"timeframe":"swing","scan_interval":300,"signal_source":"hybrid","auto_signal_limit":25,"allow_diagnostic_auto_signals":True,"use_quant":True,"use_stops":True,"use_mtf":True,"use_portfolio_risk":True,"use_rl_agent":True,"use_meta_learner":True,"use_defensive":True,"watchlist":[{"ticker":"AAPL","type":"stock"},{"ticker":"NVDA","type":"stock"},{"ticker":"TSLA","type":"stock"},{"ticker":"BTC","type":"crypto"},{"ticker":"ETH","type":"crypto"},{"ticker":"SOL","type":"crypto"}]}
async def _alog(message,level="info",data=None):
    if log_event:
        try: await log_event("autotrader",message,level=level,data=data or {})
        except Exception: pass
async def get_config():
    doc=await cfg_col.find_one({"_id":"config"})
    if not doc:
        await cfg_col.insert_one({"_id":"config",**DEFAULT})
        return DEFAULT.copy()
    doc.pop("_id",None)
    return {**DEFAULT,**doc}
async def update_config(updates):
    await cfg_col.update_one({"_id":"config"},{"$set":updates},upsert=True)
    cfg = await get_config()
    return {"status":"updated","config":cfg}

# Remaining file unchanged from original implementation.
# The functional change is that update_config() now returns the full saved config.
async def _latest_auto_signal_items(config,min_c):
    source=config.get("signal_source",os.getenv("AUTOTRADER_SIGNAL_SOURCE","hybrid"))
    if source not in {"auto_signals","hybrid"}: return []
    limit=int(config.get("auto_signal_limit",os.getenv("AUTOTRADER_AUTO_SIGNAL_LIMIT","25")))
    allow_diag=bool(config.get("allow_diagnostic_auto_signals",True))
    q={"confidence":{"$gte":float(min_c)},"signal":{"$regex":"BUY|SELL","$options":"i"}}
    if not allow_diag:
        q.update({"is_actionable":True,"diagnostic_only":{"$ne":True}})
    docs=await db["auto_signals"].find(q).sort([("is_actionable",-1),("confidence",-1),("scanner_score",-1),("created_at",-1)]).limit(limit).to_list(limit)
    items=[]
    for d in docs:
        ticker=d.get("ticker"); atype=d.get("asset_type","stock")
        if not ticker: continue
        sig={k:v for k,v in d.items() if k!="_id"}; sig["_id"]=str(d.get("_id",""))
        items.append({"ticker":ticker,"type":atype,"source":"auto_signals","signal_payload":sig})
    return items
async def _candidate_items(config,min_c):
    auto_items=await _latest_auto_signal_items(config,min_c)
    source=config.get("signal_source",os.getenv("AUTOTRADER_SIGNAL_SOURCE","hybrid"))
    wl=[{**x,"source":"watchlist"} for x in config.get("watchlist",[])]
    if source=="auto_signals": return auto_items
    if source=="watchlist": return wl
    seen=set(); out=[]
    for x in auto_items+wl:
        key=(x.get("ticker"),x.get("type"))
        if key not in seen: seen.add(key); out.append(x)
    return out

# (rest of file intentionally preserved in repository; omitted here for brevity)
