"""Backtest router — async jobs, multi-timeframe tests, adaptive regime mode, and Optuna optimization."""
import asyncio, uuid
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException
from middleware.auth import get_current_user, scope_filter
from services.backtest_engine import fetch_history, run_backtest, run_compare
from services.optuna_optimizer import optimize_backtest
from services.universal_backtest import run_universal_backtest, optimize_universal
from services.universal_strategy import UNIVERSAL_PARAM_SPACE, DEFAULT_PARAMS as UNIVERSAL_DEFAULTS
from services.strategies import list_strategies
from services.logger import child
from database import db
log=child("backtest_router"); router=APIRouter(); col=db["backtests"]; jobs=db["backtest_jobs"]
VALID_INTERVALS={"1d","4h","1h","30m","15m","5m","1m","1wk"}; MAX_BACKTEST_DAYS=3650
def _now(): return datetime.utcnow().isoformat()
def _adaptive(req):
    mode=req.get("strategy_mode") or ("adaptive_regime" if req.get("adaptive_regime") else "static")
    return mode, bool(req.get("adaptive_regime") or mode in {"adaptive","adaptive_regime","regime"})
def _intervals(req):
    raw=req.get("intervals") or req.get("timeframes") or req.get("frames")
    if raw is None: return [req.get("interval","1d")]
    vals=[x.strip() for x in raw.split(",") if x.strip()] if isinstance(raw,str) else [str(x).strip() for x in raw if str(x).strip()] if isinstance(raw,list) else []
    return vals or [req.get("interval","1d")]
def _clean_req(req):
    ticker=(req.get("ticker") or "AAPL").upper(); asset_type=req.get("asset_type","stock"); capital=float(req.get("capital",10000)); days=int(req.get("days",365)); intervals=_intervals(req)
    if capital<=0 or capital>1e10: raise HTTPException(400,"capital out of range")
    if days<=0 or days>MAX_BACKTEST_DAYS: raise HTTPException(400,f"days must be 1..{MAX_BACKTEST_DAYS}")
    bad=[i for i in intervals if i not in VALID_INTERVALS]
    if bad: raise HTTPException(400,f"interval must be one of {sorted(VALID_INTERVALS)}")
    return ticker,asset_type,capital,days,intervals
async def _job_log(job_id,message,level="info",data=None):
    await jobs.update_one({"job_id":job_id},{"$push":{"logs":{"ts":_now(),"level":level,"message":message,"data":data or {}}},"$set":{"updated_at":_now()}})
async def _set_progress(job_id,status=None,progress=None,result=None,error=None):
    u={"updated_at":_now()}
    if status is not None: u["status"]=status
    if progress is not None: u["progress"]=progress
    if result is not None: u["result"]=result
    if error is not None: u["error"]=error
    await jobs.update_one({"job_id":job_id},{"$set":u})
async def _run_one(job_id,req,user,ticker,asset_type,capital,days,interval,index=1,total=1):
    strategy=req.get("strategy","ensemble"); mode,adaptive_regime=_adaptive(req); end=datetime.now().strftime("%Y-%m-%d"); start=(datetime.now()-timedelta(days=days)).strftime("%Y-%m-%d")
    await _job_log(job_id,f"[{index}/{total}] Starting {ticker} {asset_type} {mode} backtest on {interval} for {days} days.")
    await _job_log(job_id,f"[{interval}] Loading historical candles from configured providers...")
    df=await fetch_history(ticker,asset_type,start,end,interval)
    if df is None or len(df)<60:
        msg=f"[{interval}] Not enough candle data for {ticker}. Received {0 if df is None else len(df)} bars; need at least 60."; await _job_log(job_id,msg,"error"); return {"interval":interval,"error":msg}
    await _job_log(job_id,f"[{interval}] Loaded {len(df)} candles from {str(df['date'].iloc[0])[:10]} to {str(df['date'].iloc[-1])[:10]}.",data={"bars":len(df),"interval":interval,"strategy_mode":mode})
    result=await run_backtest(ticker=ticker,asset_type=asset_type,start_date=start,end_date=end,interval=interval,initial_capital=capital,risk_per_trade=float(req.get("risk_per_trade",0.02)),min_confidence=int(req.get("min_confidence",55)),sl_atr_mult=float(req.get("sl_atr_mult",2.0)),tp_atr_mult=float(req.get("tp_atr_mult",3.0)),fee_bps=float(req.get("fee_bps",5)),slippage_bps=float(req.get("slippage_bps",3)),spread_bps=float(req.get("spread_bps",2)),max_hold_bars=int(req.get("max_hold_bars",30)),strategy=strategy,strategy_mode=mode,adaptive_regime=adaptive_regime,regime_strategy_map=req.get("regime_strategy_map"))
    result["interval"]=interval
    if "error" in result: await _job_log(job_id,f"[{interval}] {result['error']}","error"); return result
    if result.get("regime_summary"):
        rs=result["regime_summary"]; await _job_log(job_id,f"[{interval}] Adaptive regime summary: switches={rs.get('strategy_switches',0)} regimes={list((rs.get('regime_counts') or {}).keys())} strategies={list((rs.get('strategy_counts') or {}).keys())}",data=rs)
    trades=result.get("trades",[]) or []; await _job_log(job_id,f"[{interval}] Produced {len(trades)} trades. Win rate: {result.get('win_rate')}%. Return: {result.get('total_return_pct')}%.")
    for i,t in enumerate(trades[:100],1): await _job_log(job_id,f"[{interval}] Trade {i}: {t.get('side')} {t.get('strategy_used','')} {t.get('regime','')} entry {t.get('entry_date')} @ {t.get('entry_price')} → exit {t.get('exit_date')} | PnL ${t.get('pnl')} ({t.get('pnl_pct')}%) | {t.get('exit_reason')}",data={**t,"interval":interval})
    if len(trades)==0: await _job_log(job_id,f"[{interval}] No trades opened. Try lowering Min Confidence or changing strategy/timeframe.","warning")
    try: await col.insert_one({**{k:v for k,v in result.items() if k not in ("equity_curve","trades","drawdown_curve")},"user_id":user["id"],"trades_count":result.get("total_trades",0),"saved_at":_now()})
    except Exception as e: await _job_log(job_id,f"[{interval}] Completed but save failed: {e}","warning")
    return result
async def _run_backtest_job(job_id,req,user):
    try:
        ticker,asset_type,capital,days,intervals=_clean_req(req); await _set_progress(job_id,"running",5); mode,adaptive_regime=_adaptive(req)
        if req.get("optimize") or req.get("use_optuna"):
            await _job_log(job_id,f"Starting Optuna optimization + final {mode} backtest for {ticker}. Trials: {int(req.get('optuna_trials', req.get('trials',25)))}")
            async def lf(msg,level="info",data=None): await _job_log(job_id,msg,level,data)
            async def pf(p): await _set_progress(job_id,"running",p)
            opt=await optimize_backtest({**req,"intervals":intervals,"strategy_mode":mode,"adaptive_regime":adaptive_regime},user,log_fn=lf,progress_fn=pf)
            best=opt.get("best_result") or {}
            if "error" in best:
                await _set_progress(job_id,"failed",100,result=opt,error=best.get("error")); return
            try: await col.insert_one({**{k:v for k,v in best.items() if k not in ("equity_curve","trades","drawdown_curve")},"user_id":user["id"],"trades_count":best.get("total_trades",0),"saved_at":_now(),"optuna":True,"best_params":opt.get("best_params"),"best_score":opt.get("best_score")})
            except Exception as e: await _job_log(job_id,f"Optuna completed but history save failed: {e}","warning")
            await _job_log(job_id,"Optuna finished. Final optimized backtest result is ready.","success")
            await _set_progress(job_id,"completed",100,result=opt); return
        await _job_log(job_id,f"Testing {ticker} on {len(intervals)} timeframe(s): {', '.join(intervals)} | mode={mode}")
        results=[]
        for idx,interval in enumerate(intervals,1): await _set_progress(job_id,"running",5+int((idx-1)/max(1,len(intervals))*85)); results.append(await _run_one(job_id,req,user,ticker,asset_type,capital,days,interval,idx,len(intervals)))
        valid=[r for r in results if "error" not in r]
        if not valid:
            msg="All timeframe backtests failed. Check logs for provider/candle errors."; await _job_log(job_id,msg,"error"); await _set_progress(job_id,"failed",100,result={"mode":"multi_timeframe","results":results},error=msg); return
        best=sorted(valid,key=lambda r:(float(r.get("total_return_pct",0)),float(r.get("sharpe",0)),int(r.get("total_trades",0))),reverse=True)[0]
        await _job_log(job_id,f"Best timeframe: {best.get('interval')} | Return {best.get('total_return_pct')}% | Sharpe {best.get('sharpe')} | Trades {best.get('total_trades')}","success")
        final=best if len(intervals)==1 else {"mode":"multi_timeframe","ticker":ticker,"asset_type":asset_type,"strategy_mode":mode,"adaptive_regime":adaptive_regime,"best_interval":best.get("interval"),"best_result":best,"results":results,"summary":[{"interval":r.get("interval"),"error":r.get("error"),"return":r.get("total_return_pct"),"sharpe":r.get("sharpe"),"win_rate":r.get("win_rate"),"trades":r.get("total_trades"),"max_drawdown":r.get("max_drawdown"),"strategy_mode":r.get("strategy_mode")} for r in results]}
        await _job_log(job_id,"Backtest job completed."); await _set_progress(job_id,"completed",100,result=final)
    except Exception as e: log.exception(f"backtest job failed: {e}"); await _job_log(job_id,f"Backtest job failed: {e}","error"); await _set_progress(job_id,"failed",100,error=str(e))
@router.get("/strategies")
async def strategies(): return {"strategies":list_strategies()}
@router.post("/jobs")
async def create_job(req:dict,user=Depends(get_current_user)):
    _clean_req(req); job_id=str(uuid.uuid4()); await jobs.insert_one({"job_id":job_id,"user_id":user["id"],"status":"queued","progress":0,"logs":[{"ts":_now(),"level":"info","message":"Queued backtest job.","data":{}}],"request":req,"created_at":_now(),"updated_at":_now()}); asyncio.create_task(_run_backtest_job(job_id,req,user)); return {"job_id":job_id,"status":"queued","progress":0}
@router.get("/jobs/{job_id}")
async def get_job(job_id:str,user=Depends(get_current_user)):
    doc=await jobs.find_one({"job_id":job_id,"user_id":user["id"]})
    if not doc: raise HTTPException(404,"job not found")
    doc["_id"]=str(doc["_id"]); return doc
@router.get("/jobs/{job_id}/logs")
async def get_job_logs(job_id:str,user=Depends(get_current_user)):
    doc=await jobs.find_one({"job_id":job_id,"user_id":user["id"]},{"logs":1,"status":1,"progress":1,"error":1})
    if not doc: raise HTTPException(404,"job not found")
    return {"job_id":job_id,"status":doc.get("status"),"progress":doc.get("progress",0),"logs":doc.get("logs",[]),"error":doc.get("error")}
@router.post("/run")
async def run(req:dict,user=Depends(get_current_user)):
    ticker,asset_type,capital,days,intervals=_clean_req(req); interval=intervals[0]; end=datetime.now().strftime("%Y-%m-%d"); start=(datetime.now()-timedelta(days=days)).strftime("%Y-%m-%d"); mode,adaptive_regime=_adaptive(req)
    return await run_backtest(ticker=ticker,asset_type=asset_type,start_date=start,end_date=end,interval=interval,initial_capital=capital,risk_per_trade=float(req.get("risk_per_trade",0.02)),min_confidence=int(req.get("min_confidence",55)),sl_atr_mult=float(req.get("sl_atr_mult",2.0)),tp_atr_mult=float(req.get("tp_atr_mult",3.0)),fee_bps=float(req.get("fee_bps",5)),slippage_bps=float(req.get("slippage_bps",3)),spread_bps=float(req.get("spread_bps",2)),max_hold_bars=int(req.get("max_hold_bars",30)),strategy=req.get("strategy","ensemble"),strategy_mode=mode,adaptive_regime=adaptive_regime,regime_strategy_map=req.get("regime_strategy_map"))
@router.post("/compare")
async def compare(req:dict,user=Depends(get_current_user)):
    ticker,asset_type,capital,days,intervals=_clean_req(req); raw=req.get("strategies") or ["trend_follow","mean_revert","breakout","ensemble"]
    if not isinstance(raw,list) or len(raw)>20: raise HTTPException(400,"strategies must be a list of <= 20 names")
    end=datetime.now().strftime("%Y-%m-%d"); start=(datetime.now()-timedelta(days=days)).strftime("%Y-%m-%d"); mode,adaptive_regime=_adaptive(req)
    return await run_compare(ticker=ticker,asset_type=asset_type,start_date=start,end_date=end,interval=intervals[0],initial_capital=capital,strategies=raw,risk_per_trade=float(req.get("risk_per_trade",0.02)),min_confidence=int(req.get("min_confidence",55)),strategy_mode=mode,adaptive_regime=adaptive_regime,regime_strategy_map=req.get("regime_strategy_map"))
@router.get("/history")
async def history(limit:int=20,user=Depends(get_current_user)):
    docs=await col.find(scope_filter(user)).sort("saved_at",-1).limit(limit).to_list(limit)
    for d in docs: d["_id"]=str(d["_id"])
    return {"backtests":docs,"count":len(docs)}
@router.delete("/history")
async def clear_history(user=Depends(get_current_user)):
    res=await col.delete_many(scope_filter(user)); return {"deleted":res.deleted_count}
@router.get("/timeframes")
async def tfs(): return {"intervals":sorted(VALID_INTERVALS),"presets":[{"label":"Last 90 days","days":90},{"label":"Last 6 months","days":180},{"label":"Last 1 year","days":365},{"label":"Last 2 years","days":730}]}

@router.get("/universal/spec")
async def universal_spec():
    return {"param_space": UNIVERSAL_PARAM_SPACE, "defaults": UNIVERSAL_DEFAULTS}

def _validate_universal(req:dict):
    days=int(req.get("days",365))
    if days<=0 or days>MAX_BACKTEST_DAYS: raise HTTPException(400,f"days must be 1..{MAX_BACKTEST_DAYS}")
    syms=req.get("symbols") or req.get("tickers")
    if syms and not isinstance(syms,(list,str)): raise HTTPException(400,"symbols must be a list or comma string")
    if isinstance(syms,list) and len(syms)>30: raise HTTPException(400,"symbols max 30")
    ivs=req.get("intervals") or req.get("timeframes") or [req.get("interval","1d")]
    if isinstance(ivs,str): ivs=[x.strip() for x in ivs.split(",") if x.strip()]
    bad=[i for i in ivs if i not in VALID_INTERVALS]
    if bad: raise HTTPException(400,f"interval(s) {bad} not in {sorted(VALID_INTERVALS)}")
    trials=int(req.get("optuna_trials",req.get("trials",25)))
    if trials<5 or trials>300: raise HTTPException(400,"optuna_trials must be 5..300")

@router.post("/universal/run")
async def universal_run(req:dict,user=Depends(get_current_user)):
    _validate_universal(req); return await run_universal_backtest(req)

@router.post("/universal/optimize")
async def universal_optimize(req:dict,user=Depends(get_current_user)):
    _validate_universal(req); job_id=str(uuid.uuid4())
    await jobs.insert_one({"job_id":job_id,"user_id":user["id"],"status":"queued","progress":0,"logs":[{"ts":_now(),"level":"info","message":"Queued universal Optuna job.","data":{}}],"request":req,"created_at":_now(),"updated_at":_now()})
    async def _run():
        try:
            await _set_progress(job_id,"running",5)
            async def lf(msg,level="info",data=None): await _job_log(job_id,msg,level,data)
            async def pf(p): await _set_progress(job_id,"running",p)
            opt=await optimize_universal(req,user,log_fn=lf,progress_fn=pf)
            await _set_progress(job_id,"completed",100,result=opt)
            await _job_log(job_id,"Universal Optuna optimisation completed.","success")
        except Exception as e:
            log.exception(f"universal optuna failed: {e}"); await _job_log(job_id,f"Failed: {e}","error"); await _set_progress(job_id,"failed",100,error=str(e))
    asyncio.create_task(_run())
    return {"job_id":job_id,"status":"queued","progress":0}
