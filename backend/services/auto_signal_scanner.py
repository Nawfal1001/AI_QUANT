"""
Automatic Universe Signal Scanner with diagnostic output.
Auto-infers broker asset coverage without requiring AUTO_SIGNAL_ASSET_TYPES_* env vars.
Supports multi-timeframe scans: scalping, intraday, swing.
"""
from __future__ import annotations
import asyncio, os
from datetime import datetime
from typing import Any, Dict, List, Optional
from database import db
from services.logger import child
from services.signal_service import generate_signal
from services.symbol_scanner import scan_universe, normalize_broker_id, infer_asset_type_for_broker
try:
    from services.activity_log import log_event
except Exception:
    log_event = None
log=child("auto_signal_scanner"); col_auto_signals=db["auto_signals"]; col_auto_signal_runs=db["auto_signal_runs"]
_TASK=None; _RUNNING=False
BROKER_CAPABILITIES={"paper":["crypto","stock","forex"],"fusion":["stock","forex","crypto"],"alpaca":["stock","crypto"],"interactive_brokers":["stock","forex","crypto"],"ibkr":["stock","forex","crypto"],"tradestation":["stock","crypto"],"schwab":["stock"],"robinhood":["stock","crypto"],"webull":["stock","crypto"],"fidelity":["stock"],"etrade":["stock"],"binance":["crypto"],"binanceus":["crypto"],"kucoin":["crypto"],"coinbase":["crypto"],"kraken":["crypto"],"bybit":["crypto"],"okx":["crypto"],"bitget":["crypto"],"oanda":["forex"],"fxcm":["forex"],"forexcom":["forex"]}
PAPER_ALIASES={"paper","fusion","sandbox","demo"}
DEFAULT_TIMEFRAME_INTERVALS={"scalping":"5m","intraday":"30m","swing":"1d","position":"1wk"}
def _env_bool(name,default=False):
    raw=os.getenv(name)
    if raw is None: return default
    return str(raw).strip().lower() in {"1","true","yes","on"}
def _csv_env(name): return [x.strip() for x in os.getenv(name,"").split(",") if x.strip()]
def _timeframes():
    vals=_csv_env("AUTO_SIGNAL_TIMEFRAMES") or _csv_env("AUTO_SIGNAL_TIMEFRAME") or ["scalping","intraday","swing"]
    out=[]
    for v in vals:
        v=v.lower().strip()
        if v and v not in out: out.append(v)
    return out or ["swing"]
def _interval_for_timeframe(tf):
    env=os.getenv(f"AUTO_SIGNAL_INTERVAL_{tf.upper()}")
    if env: return env.strip()
    if os.getenv("AUTO_SIGNAL_TIMEFRAMES") is None and os.getenv("AUTO_SIGNAL_TIMEFRAME") and os.getenv("AUTO_SIGNAL_INTERVAL"):
        return os.getenv("AUTO_SIGNAL_INTERVAL","1d")
    return DEFAULT_TIMEFRAME_INTERVALS.get(tf,"1d")
async def _alog(scope,message,level="info",data=None):
    if log_event:
        try: await log_event(scope,message,level=level,data=data or {})
        except Exception: pass
def _execution_mode_for_broker(broker):
    b=normalize_broker_id(broker)
    if b in PAPER_ALIASES: return "paper"
    return "live" if _env_bool("LIVE_TRADING_ENABLED",False) else "paper"
async def _configured_brokers():
    explicit=_csv_env("AUTO_SIGNAL_BROKERS"); out=[normalize_broker_id(x) for x in explicit if x] if explicit else []
    if not out:
        for coll,field in [("brokers","broker_id"),("bots","broker")]:
            try:
                for x in await db[coll].distinct(field):
                    nb=normalize_broker_id(x)
                    if nb and nb not in out: out.append(nb)
            except Exception: pass
    if _env_bool("BINANCE_ENABLED",False) or os.getenv("BINANCE_API_KEY") or os.getenv("BINANCE_SECRET_KEY"):
        if "binance" not in out: out.append("binance")
    if os.getenv("ALPACA_API_KEY") or os.getenv("APCA_API_KEY_ID"):
        if "alpaca" not in out: out.append("alpaca")
    if os.getenv("OANDA_API_KEY") or os.getenv("OANDA_TOKEN"):
        if "oanda" not in out: out.append("oanda")
    if not out: out=["paper","fusion"]
    if "paper" not in out: out.insert(0,"paper")
    return out
def _asset_types_for_broker(broker):
    broker=normalize_broker_id(broker)
    explicit=_csv_env(f"AUTO_SIGNAL_ASSET_TYPES_{broker.upper()}")
    if explicit: return [x.lower() for x in explicit]
    return BROKER_CAPABILITIES.get(broker,[infer_asset_type_for_broker(broker)])
def _signal_direction(signal):
    s=str(signal or "HOLD").upper(); return "BUY" if "BUY" in s else "SELL" if "SELL" in s else "HOLD"
def _filter_reason(x,min_confidence):
    if x.get("error"): return "provider_or_signal_error"
    if x.get("direction")=="HOLD": return "hold_signal"
    if float(x.get("confidence",0) or 0)<min_confidence: return "below_min_confidence"
    return "actionable"
async def scan_auto_signals(broker_id="paper",asset_type=None,timeframe="swing",interval="1d",scan_limit=20,signal_limit=10,min_confidence=55,use_ai=True,discover=True,execution_mode=None):
    broker=normalize_broker_id(broker_id); asset=asset_type or infer_asset_type_for_broker(broker); execution_mode=execution_mode or _execution_mode_for_broker(broker); started=datetime.utcnow().isoformat()
    await _alog("signals",f"Starting auto scan {broker}/{execution_mode}/{asset} interval={interval} timeframe={timeframe} min_conf={min_confidence}")
    scan=await scan_universe(asset_type=asset,interval=interval,limit=scan_limit,use_ai=use_ai,discover=discover,broker_id=broker)
    candidates=scan.get("selected",[])[:scan_limit]
    await _alog("signals",f"Universe scan {broker}/{execution_mode}/{asset}/{timeframe}: {len(candidates)} candidates selected",data={"broker":broker,"mode":execution_mode,"asset_type":asset,"timeframe":timeframe,"interval":interval,"candidate_count":len(candidates)})
    generated=[]
    for candidate in candidates:
        ticker=candidate.get("ticker")
        if not ticker: continue
        try:
            sig=await generate_signal(ticker,asset,timeframe,use_ai=use_ai)
            sig.update({"broker":broker,"execution_mode":execution_mode,"scanner_score":candidate.get("score"),"scanner_reason":candidate.get("reason"),"auto_signal":True,"created_at":datetime.utcnow().isoformat(),"direction":_signal_direction(sig.get("signal")),"strategy_mode":timeframe,"timeframe":timeframe,"interval":interval})
        except Exception as e:
            sig={"ticker":ticker,"asset_type":asset,"broker":broker,"execution_mode":execution_mode,"signal":"HOLD","confidence":0,"error":str(e),"created_at":datetime.utcnow().isoformat(),"direction":"HOLD","scanner_score":candidate.get("score"),"scanner_reason":candidate.get("reason"),"strategy_mode":timeframe,"timeframe":timeframe,"interval":interval}
        sig["is_actionable"]=sig.get("direction") in {"BUY","SELL"} and float(sig.get("confidence",0) or 0)>=float(min_confidence); sig["filter_reason"]=_filter_reason(sig,min_confidence); generated.append(sig)
        await _alog("signals",f"{broker}/{execution_mode}/{asset}/{timeframe} {ticker}: {sig.get('signal')} conf={sig.get('confidence')} reason={sig.get('filter_reason')}","success" if sig["is_actionable"] else "info",{"ticker":ticker,"broker":broker,"mode":execution_mode,"asset_type":asset,"timeframe":timeframe,"interval":interval,"signal":sig.get("signal"),"confidence":sig.get("confidence"),"reason":sig.get("filter_reason")})
    actionable=[x for x in generated if x.get("is_actionable")]; actionable.sort(key=lambda x:(float(x.get("confidence",0) or 0),float(x.get("scanner_score",0) or 0)),reverse=True)
    diagnostics=sorted(generated,key=lambda x:(1 if x.get("is_actionable") else 0,float(x.get("confidence",0) or 0),float(x.get("scanner_score",0) or 0)),reverse=True)[:signal_limit]
    best=actionable[:signal_limit]; store=best if best else diagnostics
    run={"broker":broker,"execution_mode":execution_mode,"asset_type":asset,"timeframe":timeframe,"strategy_mode":timeframe,"interval":interval,"scan_limit":scan_limit,"signal_limit":signal_limit,"min_confidence":min_confidence,"use_ai":use_ai,"discover":discover,"started_at":started,"finished_at":datetime.utcnow().isoformat(),"candidate_count":len(candidates),"generated_count":len(generated),"actionable_count":len(actionable),"best":best,"diagnostics":diagnostics,"stored_count":len(store)}
    await col_auto_signal_runs.insert_one(dict(run)); await col_auto_signals.delete_many({"broker":broker,"execution_mode":execution_mode,"asset_type":asset,"timeframe":timeframe})
    if store: await col_auto_signals.insert_many([{**x,"timeframe":timeframe,"strategy_mode":timeframe,"interval":interval,"broker":broker,"execution_mode":execution_mode,"asset_type":asset,"diagnostic_only":not x.get("is_actionable")} for x in store])
    await _alog("signals",f"Finished auto scan {broker}/{execution_mode}/{asset}/{timeframe}: candidates={len(candidates)} generated={len(generated)} actionable={len(actionable)} stored={len(store)}","success" if store else "warning",run)
    run.pop("_id",None); return run
async def scan_all_auto_signals():
    brokers=await _configured_brokers(); timeframes=_timeframes(); scan_limit=int(os.getenv("AUTO_SIGNAL_SCAN_LIMIT","20")); signal_limit=int(os.getenv("AUTO_SIGNAL_LIMIT","10")); min_confidence=float(os.getenv("AUTO_SIGNAL_MIN_CONFIDENCE","55")); max_parallel=int(os.getenv("AUTO_SIGNAL_MAX_PARALLEL","4")); use_ai=_env_bool("AUTO_SIGNAL_USE_AI",True); discover=_env_bool("AUTO_SIGNAL_DISCOVER_UNIVERSE",True)
    jobs=[(b,_execution_mode_for_broker(b),a,tf,_interval_for_timeframe(tf)) for b in brokers for a in _asset_types_for_broker(b) for tf in timeframes]; sem=asyncio.Semaphore(max(1,max_parallel))
    await _alog("signals",f"Full scan plan: {len(jobs)} broker/mode/asset/timeframe runs",data={"timeframes":timeframes,"jobs":[{"broker":b,"mode":m,"asset_type":a,"timeframe":tf,"interval":iv} for b,m,a,tf,iv in jobs]})
    async def _one(broker,mode,asset,tf,iv):
        async with sem:
            try: return await scan_auto_signals(broker,asset,tf,iv,scan_limit,signal_limit,min_confidence,use_ai,discover,mode)
            except Exception as e:
                await _alog("signals",f"auto signal scan failed for {broker}/{mode}/{asset}/{tf}: {e}","error"); log.warning(f"auto signal scan failed for {broker}/{mode}/{asset}/{tf}: {e}"); return {"broker":broker,"execution_mode":mode,"asset_type":asset,"timeframe":tf,"interval":iv,"error":str(e),"finished_at":datetime.utcnow().isoformat()}
    runs=await asyncio.gather(*(_one(b,m,a,tf,iv) for b,m,a,tf,iv in jobs)); return {"brokers":brokers,"timeframes":timeframes,"runs":list(runs),"finished_at":datetime.utcnow().isoformat()}
async def latest_auto_signals(broker_id=None,asset_type=None,limit=50,execution_mode=None,timeframe=None):
    q={}
    if broker_id: q["broker"]=normalize_broker_id(broker_id)
    if asset_type: q["asset_type"]=asset_type
    if execution_mode: q["execution_mode"]=execution_mode
    if timeframe: q["timeframe"]=timeframe
    docs=await col_auto_signals.find(q).sort([("is_actionable",-1),("confidence",-1),("created_at",-1)]).limit(limit).to_list(limit)
    for d in docs: d["_id"]=str(d["_id"])
    return docs
async def _loop(interval_sec):
    global _RUNNING; _RUNNING=True; log.info(f"auto_signal_scanner started interval={interval_sec}s")
    while _RUNNING:
        try: await scan_all_auto_signals()
        except Exception as e: log.warning(f"auto signal scanner loop failed: {e}"); await _alog("signals",f"auto signal scanner loop failed: {e}","error")
        await asyncio.sleep(interval_sec)
async def start_auto_signal_scanner(interval_sec=None):
    global _TASK
    if _TASK and not _TASK.done(): return
    if not _env_bool("AUTO_SIGNAL_SCANNER_ENABLED",True): log.info("auto_signal_scanner disabled"); return
    _TASK=asyncio.create_task(_loop(interval_sec or int(os.getenv("AUTO_SIGNAL_SCAN_INTERVAL_SEC","900"))))
def stop_auto_signal_scanner():
    global _RUNNING,_TASK; _RUNNING=False
    if _TASK: _TASK.cancel(); _TASK=None
