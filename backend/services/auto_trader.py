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
    if not doc: await cfg_col.insert_one({"_id":"config",**DEFAULT}); return DEFAULT.copy()
    doc.pop("_id",None); return {**DEFAULT,**doc}
async def update_config(updates):
    await cfg_col.update_one({"_id":"config"},{"$set":updates},upsert=True); cfg=await get_config(); return {"status":"updated","config":cfg}
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
async def scan_and_execute():
    config=await get_config()
    if not config.get("enabled"): return {"status":"disabled"}
    try:
        from services.runtime_controls import is_auto_trader_enabled
        if not await is_auto_trader_enabled(): return {"status":"disabled_runtime","reason":"auto_trader_enabled is off in runtime controls"}
    except Exception as _e: _log.debug(f"runtime_controls check skipped: {_e}")
    defensive_adj={"halt_trading":False,"size_multiplier":1.0,"min_confidence":config.get("min_confidence",70),"allowed_regimes":None}
    if config.get("use_defensive",True):
        try:
            from services.defensive_mode import check_defensive_mode
            ds=await check_defensive_mode(); defensive_adj=ds.get("adjustments",defensive_adj)
            if defensive_adj.get("halt_trading"): return {"status":"halted_defensive","reason":ds.get("reason","Defensive halt"),"mode":ds.get("mode","HALT")}
        except Exception as _e: _log.debug(f"ignored: {_e}")
    tf=config.get("timeframe","swing"); min_c=defensive_adj.get("min_confidence",config.get("min_confidence",70)); size_mult=defensive_adj.get("size_multiplier",1.0); allowed_regimes=defensive_adj.get("allowed_regimes"); capital=config.get("capital",10000); max_t=config.get("max_open",5); open_cnt=await trades_col.count_documents({"status":"open"})
    if open_cnt>=max_t: return {"status":"max_trades_reached","open":open_cnt,"executed":0,"trades":[],"skipped":[{"reason":"max_open_reached"}]}
    from services.defensive_mode import calculate_recent_pnl
    pnl_24h=await calculate_recent_pnl(24)
    items=await _candidate_items(config,min_c)
    await _alog(f"Auto-trader scan source={config.get('signal_source','hybrid')} candidates={len(items)} min_conf={min_c}",data={"candidates":len(items),"min_confidence":min_c})
    executed=[]; rl_decisions=[]; skipped=[]
    for item in items:
        if open_cnt>=max_t: break
        ticker=item["ticker"]; atype=item.get("type","stock")
        if await trades_col.find_one({"ticker":ticker,"status":"open"}): skipped.append({"ticker":ticker,"reason":"already_open"}); continue
        if item.get("source")=="auto_signals" and item.get("signal_payload"):
            sig=item["signal_payload"]; sig.setdefault("ticker",ticker); sig.setdefault("asset_type",atype); sig.setdefault("timeframe",sig.get("timeframe",tf)); sig.setdefault("regime",sig.get("regime","RANGING")); sig.setdefault("atr", abs(float(sig.get("price",1) or 1)-float(sig.get("sl",0) or 0)) or float(sig.get("price",1) or 1)*0.02)
        else:
            try: sig=await generate_signal(ticker,atype,tf,use_advanced=True)
            except Exception as e: skipped.append({"ticker":ticker,"reason":str(e)}); continue
        conf=float(sig.get("confidence",0) or 0)
        sig_txt=str(sig.get("signal","")).upper()
        if conf<float(min_c): skipped.append({"ticker":ticker,"reason":"below_confidence","confidence":conf,"min_confidence":min_c}); continue
        if "BUY" not in sig_txt and "SELL" not in sig_txt: skipped.append({"ticker":ticker,"reason":"not_buy_sell","signal":sig.get("signal")}); continue
        regime=sig.get("regime","RANGING")
        if allowed_regimes and regime not in allowed_regimes: skipped.append({"ticker":ticker,"reason":"regime_blocked","regime":regime}); continue
        meta=sig.get("meta_learner",{}) or {}
        if item.get("source")!="auto_signals" and config.get("use_meta_learner",True) and meta.get("available") and meta.get("recommend")=="SKIP": skipped.append({"ticker":ticker,"reason":"meta_skip"}); continue
        history=await hist_col.find({}).sort("closed_at",-1).limit(50).to_list(50); wins=[t["pnl_pct"] for t in history if t.get("outcome")=="WIN" and t.get("pnl_pct")]; losses=[t["pnl_pct"] for t in history if t.get("outcome")=="LOSS" and t.get("pnl_pct")]; wr=len(wins)/len(history) if history else 0.55; aw=sum(wins)/len(wins) if wins else 2.0; al=sum(losses)/len(losses) if losses else -1.5; trade_ret=[t.get("pnl_pct",0) for t in history]; eq=[capital]; r=capital
        for t in history: r=r*(1+t.get("pnl_pct",0)/100); eq.append(r)
        rl_size_mult=1.0; rl_state_key=None; rl_action_idx=None
        if item.get("source")!="auto_signals" and config.get("use_rl_agent",True):
            try:
                from services.rl_agent import get_action
                atr_pct=sig.get("atr",0)/float(sig.get("price",1))*100 if sig.get("price") else 1.0; rl_decision=await get_action(regime,sig["confidence"],atr_pct,pnl_24h["total_pnl"],open_cnt,epsilon=0.05); rl_decisions.append({"ticker":ticker,"action":rl_decision["action"]})
                if rl_decision["action"]=="SKIP": skipped.append({"ticker":ticker,"reason":"rl_skip"}); continue
                rl_size_mult=rl_decision["size_multiplier"]; rl_state_key=rl_decision["state_key"]; rl_action_idx=rl_decision["action_idx"]
            except Exception as e: _log.debug(f"ignored: {e}")
        if config.get("use_quant",True):
            try: pos_pct=(await optimal_position(ticker,atype,sig["signal"],capital,wr,aw,al,regime,trade_ret,eq))["recommended_pct"]
            except Exception: pos_pct=config.get("risk_per_trade",2.0)
        else: pos_pct=config.get("risk_per_trade",2.0)
        pos_pct=pos_pct*rl_size_mult*size_mult
        final_sig=sig["signal"]; final_conf=conf
        entry=float(sig.get("price") or sig.get("entry_price") or 0)
        if entry<=0: skipped.append({"ticker":ticker,"reason":"missing_price"}); continue
        qty=capital*(pos_pct/100)/entry; atr_val=float(sig.get("atr") or entry*0.02)
        if config.get("use_stops",True) and item.get("source")!="auto_signals": sl=optimal_trailing_stop(entry,entry,atr_val,0,200,"long" if "BUY" in final_sig else "short")["optimal_stop"]
        else: sl=float(sig.get("sl") or entry*(0.97 if "BUY" in final_sig else 1.03))
        tp=float(sig.get("tp") or entry*(1.06 if "BUY" in final_sig else 0.94))
        trade={"ticker":ticker,"asset_type":atype,"signal":final_sig,"confidence":final_conf,"entry_price":entry,"quantity":round(qty,6),"position_value":round(capital*pos_pct/100,2),"position_pct":round(pos_pct,2),"sl":round(sl,4),"tp":round(tp,4),"atr":round(atr_val,4),"regime":regime,"timeframe":sig.get("timeframe",tf),"status":"open","paper_mode":config.get("paper_mode",True),"opened_at":datetime.utcnow().isoformat(),"source":item.get("source"),"auto_signal_id":str(sig.get("_id","")),"diagnostic_source":bool(sig.get("diagnostic_only")),"scanner_score":sig.get("scanner_score"),"quant_powered":config.get("use_quant",True),"rl_state":rl_state_key,"rl_action":rl_action_idx,"rl_size_mult":rl_size_mult,"meta_p_win":meta.get("p_win",None),"indicators_at_entry":sig.get("indicators",[]),"enhancements_at_entry":sig.get("enhancements",{}),"entropy_tradeable":next((i.get("tradeable",True) for i in sig.get("indicators",[]) if i.get("indicator")=="ENTROPY"),True)}
        await trades_col.insert_one(trade); executed.append({"ticker":ticker,"signal":final_sig,"entry":entry,"size":round(pos_pct,2),"source":item.get("source"),"confidence":final_conf}); open_cnt+=1
        await _alog(f"Opened paper trade from {item.get('source')}: {final_sig} {ticker} conf={final_conf} entry={entry}","success",executed[-1])
    return {"status":"scanned","source":config.get("signal_source","hybrid"),"candidates":len(items),"executed":len(executed),"trades":executed,"skipped":skipped[:50],"rl_decisions":rl_decisions,"defensive_mode":defensive_adj}
async def monitor_open():
    trades=await trades_col.find({"status":"open"}).to_list(100)
    if not trades: return {"monitored":0}
    from services import data_freshness
    from services.backtest_engine import fetch_history
    closed=[]
    for trade in trades:
        ticker=trade["ticker"]; atype=trade.get("asset_type","stock"); entry=float(trade.get("entry_price",0)); sl=float(trade.get("sl",0)); tp=float(trade.get("tp",0)); sig=trade.get("signal","BUY"); price=0.0; cached=data_freshness.get_price(ticker)
        if cached and not cached.get("expired"): price=float(cached.get("price",0) or 0)
        if price<=0:
            try:
                end_dt=datetime.utcnow(); start_dt=end_dt-timedelta(days=2); df=await fetch_history(ticker,atype,start_dt.strftime("%Y-%m-%d"),end_dt.strftime("%Y-%m-%d"),"1h")
                if df is not None and len(df): price=float(df["close"].iloc[-1])
            except Exception as e: _log.debug(f"monitor price fetch failed for {ticker}: {e}"); continue
        if price<=0: continue
        hit_sl=price<=sl if "BUY" in sig else price>=sl; hit_tp=price>=tp if "BUY" in sig else price<=tp
        if hit_sl or hit_tp:
            pnl=(price-entry)/entry*100 if "BUY" in sig else (entry-price)/entry*100; outcome="WIN" if hit_tp else "LOSS"; close_reason="TP" if hit_tp else "SL"
            await trades_col.update_one({"_id":trade["_id"]},{"$set":{"status":"closed","close_price":price,"close_reason":close_reason,"pnl_pct":round(pnl,3),"outcome":outcome,"closed_at":datetime.utcnow().isoformat()}})
            await hist_col.insert_one({**{k:v for k,v in trade.items() if k!="_id"},"close_price":price,"pnl_pct":round(pnl,3),"outcome":outcome,"closed_at":datetime.utcnow().isoformat()}); closed.append({"ticker":ticker,"outcome":outcome,"pnl":round(pnl,3)})
    return {"monitored":len(trades),"closed":len(closed),"details":closed}
_running=False
async def start_scheduler():
    global _running
    if _running: return {"status":"already_running"}
    _running=True; asyncio.create_task(_loop()); return {"status":"started"}
async def stop_scheduler():
    global _running; _running=False; return {"status":"stopped"}
async def _loop():
    while _running:
        try: await scan_and_execute(); await monitor_open()
        except Exception as e: print(f"[AT] {e}"); await _alog(f"Auto-trader loop error: {e}","error")
        config=await get_config(); await asyncio.sleep(config.get("scan_interval",300))
