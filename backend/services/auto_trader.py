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
# Profile presets — applied (without overwriting user-set values) when profile is selected.
# Each preset tunes timeframe, max_hold_bars, scan cadence, min_confidence, and risk_per_trade.
PROFILE_PRESETS={
    "scalping":{"timeframe":"scalping","scan_interval":120,"min_confidence":72,"risk_per_trade":1.0,"max_hold_bars":12,"sl_atr_mult":1.2,"tp_atr_mult":1.8,"mtf_gate":"strict","partial_tp_atr":1.0,"trail_after_partial":True},
    "intraday":{"timeframe":"intraday","scan_interval":300,"min_confidence":68,"risk_per_trade":1.5,"max_hold_bars":30,"sl_atr_mult":1.8,"tp_atr_mult":2.6,"mtf_gate":"soft","partial_tp_atr":1.2,"trail_after_partial":True},
    "swing":{"timeframe":"swing","scan_interval":900,"min_confidence":65,"risk_per_trade":2.0,"max_hold_bars":60,"sl_atr_mult":2.5,"tp_atr_mult":4.0,"mtf_gate":"soft","partial_tp_atr":1.5,"trail_after_partial":True},
    "position":{"timeframe":"position","scan_interval":3600,"min_confidence":62,"risk_per_trade":2.5,"max_hold_bars":150,"sl_atr_mult":3.5,"tp_atr_mult":6.0,"mtf_gate":"off","partial_tp_atr":2.0,"trail_after_partial":True},
}
DEFAULT={"enabled":False,"paper_mode":True,"profile":"swing","leverage":1.0,"min_confidence":70,"max_open":5,"risk_per_trade":2.0,"capital":10000,"timeframe":"swing","scan_interval":300,"signal_source":"hybrid","auto_signal_limit":25,"allow_diagnostic_auto_signals":True,"use_quant":True,"use_stops":True,"use_mtf":True,"use_portfolio_risk":True,"use_rl_agent":True,"use_meta_learner":True,"use_defensive":True,"mtf_gate":"soft","partial_tp_atr":1.5,"trail_after_partial":True,"use_bayesian_online":True,"use_meta_labeler":True,"meta_labeler_threshold":0.45,"meta_labeler_retrain_every":25,"watchlist":[{"ticker":"AAPL","type":"stock"},{"ticker":"NVDA","type":"stock"},{"ticker":"TSLA","type":"stock"},{"ticker":"BTC","type":"crypto"},{"ticker":"ETH","type":"crypto"},{"ticker":"SOL","type":"crypto"}]}
def _clamp_leverage(v,lo=1.0,hi=125.0):
    try: x=float(v)
    except Exception: return 1.0
    return max(lo,min(hi,x))
async def _alog(message,level="info",data=None):
    if log_event:
        try: await log_event("autotrader",message,level=level,data=data or {})
        except Exception: pass
async def get_config():
    doc=await cfg_col.find_one({"_id":"config"})
    if not doc: await cfg_col.insert_one({"_id":"config",**DEFAULT}); return DEFAULT.copy()
    doc.pop("_id",None); return {**DEFAULT,**doc}
async def update_config(updates):
    if "profile" in updates:
        prof=str(updates["profile"]).lower()
        if prof in PROFILE_PRESETS:
            updates["profile"]=prof
            # Apply preset only for keys the user has not explicitly overridden in this patch.
            for k,v in PROFILE_PRESETS[prof].items():
                updates.setdefault(k,v)
    if "leverage" in updates:
        updates["leverage"]=_clamp_leverage(updates["leverage"])
    await cfg_col.update_one({"_id":"config"},{"$set":updates},upsert=True); cfg=await get_config(); return {"status":"updated","config":cfg}
async def _latest_auto_signal_items(config,min_c):
    source=config.get("signal_source",os.getenv("AUTOTRADER_SIGNAL_SOURCE","hybrid"))
    if source not in {"auto_signals","hybrid"}: return []
    limit=int(config.get("auto_signal_limit",os.getenv("AUTOTRADER_AUTO_SIGNAL_LIMIT","25")))
    allow_diag=bool(config.get("allow_diagnostic_auto_signals",True))
    q={"confidence":{"$gte":float(min_c)},"signal":{"$regex":"BUY|SELL","$options":"i"}}
    if not allow_diag:
        q.update({"is_actionable":True,"diagnostic_only":{"$ne":True}})
    # Profile-aware ordering: signals matching the profile's primary timeframe come first.
    profile=(config.get("profile") or "").lower()
    try:
        from services.auto_signal_scanner import PROFILE_TIMEFRAMES
        preferred_tfs=PROFILE_TIMEFRAMES.get(profile,[])
    except Exception:
        preferred_tfs=[]
    docs=await db["auto_signals"].find(q).sort([("is_actionable",-1),("confidence",-1),("scanner_score",-1),("created_at",-1)]).limit(limit*3 if preferred_tfs else limit).to_list(limit*3 if preferred_tfs else limit)
    if preferred_tfs:
        rank={tf:i for i,tf in enumerate(preferred_tfs)}
        docs.sort(key=lambda d:(rank.get(str(d.get("timeframe","")).lower(),99),-(float(d.get("confidence",0) or 0))))
        docs=docs[:limit]
    items=[]
    for d in docs:
        ticker=d.get("ticker"); atype=d.get("asset_type","stock")
        if not ticker: continue
        sig={k:v for k,v in d.items() if k!="_id"}; sig["_id"]=str(d.get("_id",""))
        items.append({"ticker":ticker,"type":atype,"source":"auto_signals","signal_payload":sig})
    return items
async def _mtf_confirmation(ticker, base_timeframe, direction):
    """Look up the most recent higher-timeframe auto_signal for the same ticker.

    Returns ("agree"|"disagree"|"missing", htf_doc_or_None). Used to gate or
    boost confidence before opening a trade.
    """
    try:
        from services.signal_service import MTF_CONFIRMATIONS
    except Exception:
        return "missing", None
    htfs = MTF_CONFIRMATIONS.get(base_timeframe, []) or []
    if not htfs:
        return "missing", None
    doc = await db["auto_signals"].find_one(
        {"ticker": ticker, "timeframe": {"$in": htfs}, "signal": {"$regex": "BUY|SELL", "$options": "i"}},
        sort=[("created_at", -1)],
    )
    if not doc:
        return "missing", None
    htf_sig = str(doc.get("signal", "")).upper()
    htf_dir = "BUY" if "BUY" in htf_sig else "SELL" if "SELL" in htf_sig else "HOLD"
    if htf_dir == "HOLD":
        return "missing", doc
    return ("agree" if htf_dir == direction else "disagree"), doc
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
        # ---- Higher-timeframe confirmation gate ----
        mtf_mode=str(config.get("mtf_gate","soft")).lower()
        mtf_status="off"; mtf_doc=None; mtf_conf_adj=0
        if mtf_mode in {"soft","strict"}:
            entry_dir="BUY" if "BUY" in sig_txt else "SELL"
            base_tf=str(sig.get("timeframe",tf) or tf).lower()
            mtf_status,mtf_doc=await _mtf_confirmation(ticker,base_tf,entry_dir)
            if mtf_status=="disagree":
                if mtf_mode=="strict":
                    skipped.append({"ticker":ticker,"reason":"mtf_disagree","htf":(mtf_doc or {}).get("timeframe"),"htf_signal":(mtf_doc or {}).get("signal")}); continue
                mtf_conf_adj=-10  # soft: dampen, still continue
            elif mtf_status=="agree":
                mtf_conf_adj=+5
            # missing → no change
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
        leverage=_clamp_leverage(config.get("leverage",1.0))
        pos_pct=pos_pct*rl_size_mult*size_mult
        final_sig=sig["signal"]; final_conf=max(0,min(95,conf+mtf_conf_adj))
        if mtf_conf_adj<0 and final_conf<float(min_c):
            skipped.append({"ticker":ticker,"reason":"mtf_soft_below_min","confidence":final_conf,"min_confidence":min_c,"htf":(mtf_doc or {}).get("timeframe")}); continue
        # ---- Bayesian online weights: scale confidence by per-indicator reliability ----
        bayes_mult=1.0; bayes_eval={"evaluated":0}
        if config.get("use_bayesian_online",True):
            try:
                from services.bayesian_online_weights import confidence_multiplier
                entry_dir="BUY" if "BUY" in sig_txt else "SELL"
                bayes_eval=await confidence_multiplier(regime,entry_dir,sig.get("indicators",[]))
                bayes_mult=float(bayes_eval.get("multiplier",1.0) or 1.0)
                final_conf=max(0,min(95,final_conf*bayes_mult))
                if final_conf<float(min_c):
                    skipped.append({"ticker":ticker,"reason":"bayesian_below_min","confidence":round(final_conf,2),"min_confidence":min_c,"multiplier":bayes_mult,"drag":bayes_eval.get("drag_terms")}); continue
            except Exception as e: _log.debug(f"bayesian online weights skipped: {e}")
        # ---- Meta-labeller gate: P(win) from learned classifier on signal metadata ----
        meta_score={"p_win":None,"kind":"disabled","ready":False}
        if config.get("use_meta_labeler",True):
            try:
                from services.meta_labeler import should_trade as meta_should_trade
                feature_row=dict(sig); feature_row["confidence"]=final_conf; feature_row["regime"]=regime; feature_row["signal"]=final_sig; feature_row["leverage"]=config.get("leverage",1.0); feature_row["mtf_status"]=mtf_status
                feature_row.setdefault("indicators_at_entry",sig.get("indicators",[]))
                meta_score=await meta_should_trade(feature_row,threshold=float(config.get("meta_labeler_threshold",0.45)))
                if meta_score.get("ready") and not meta_score.get("allow"):
                    skipped.append({"ticker":ticker,"reason":"meta_labeler_reject","p_win":meta_score.get("p_win"),"threshold":meta_score.get("threshold")}); continue
            except Exception as e: _log.debug(f"meta labeler gate skipped: {e}")
        entry=float(sig.get("price") or sig.get("entry_price") or 0)
        if entry<=0: skipped.append({"ticker":ticker,"reason":"missing_price"}); continue
        # Leverage multiplies notional exposure for a given margin (position_pct of capital).
        qty=capital*(pos_pct/100)*leverage/entry; atr_val=float(sig.get("atr") or entry*0.02)
        if config.get("use_stops",True) and item.get("source")!="auto_signals": sl=optimal_trailing_stop(entry,entry,atr_val,0,200,"long" if "BUY" in final_sig else "short")["optimal_stop"]
        else: sl=float(sig.get("sl") or entry*(0.97 if "BUY" in final_sig else 1.03))
        tp=float(sig.get("tp") or entry*(1.06 if "BUY" in final_sig else 0.94))
        trade={"ticker":ticker,"asset_type":atype,"signal":final_sig,"confidence":final_conf,"entry_price":entry,"quantity":round(qty,6),"original_quantity":round(qty,6),"position_value":round(capital*pos_pct/100*leverage,2),"margin_used":round(capital*pos_pct/100,2),"leverage":leverage,"profile":config.get("profile"),"position_pct":round(pos_pct,2),"sl":round(sl,4),"initial_sl":round(sl,4),"tp":round(tp,4),"atr":round(atr_val,4),"partial_taken":False,"realized_pnl_pct":0.0,"trailing_active":False,"mtf_status":mtf_status,"mtf_htf_timeframe":(mtf_doc or {}).get("timeframe"),"mtf_htf_signal":(mtf_doc or {}).get("signal"),"mtf_confidence_adj":mtf_conf_adj,"bayes_multiplier":round(bayes_mult,4),"bayes_evaluated":bayes_eval.get("evaluated",0),"meta_p_win":meta_score.get("p_win"),"meta_kind":meta_score.get("kind"),"regime":regime,"timeframe":sig.get("timeframe",tf),"status":"open","paper_mode":config.get("paper_mode",True),"opened_at":datetime.utcnow().isoformat(),"source":item.get("source"),"auto_signal_id":str(sig.get("_id","")),"diagnostic_source":bool(sig.get("diagnostic_only")),"scanner_score":sig.get("scanner_score"),"quant_powered":config.get("use_quant",True),"rl_state":rl_state_key,"rl_action":rl_action_idx,"rl_size_mult":rl_size_mult,"meta_learner_p_win":meta.get("p_win",None),"indicators_at_entry":sig.get("indicators",[]),"enhancements_at_entry":sig.get("enhancements",{}),"entropy_tradeable":next((i.get("tradeable",True) for i in sig.get("indicators",[]) if i.get("indicator")=="ENTROPY"),True)}
        await trades_col.insert_one(trade); executed.append({"ticker":ticker,"signal":final_sig,"entry":entry,"size":round(pos_pct,2),"source":item.get("source"),"confidence":final_conf}); open_cnt+=1
        await _alog(f"Opened paper trade from {item.get('source')}: {final_sig} {ticker} conf={final_conf} entry={entry}","success",executed[-1])
    return {"status":"scanned","source":config.get("signal_source","hybrid"),"candidates":len(items),"executed":len(executed),"trades":executed,"skipped":skipped[:50],"rl_decisions":rl_decisions,"defensive_mode":defensive_adj}
async def monitor_open():
    trades=await trades_col.find({"status":"open"}).to_list(100)
    if not trades: return {"monitored":0}
    from services import data_freshness
    from services.backtest_engine import fetch_history
    config=await get_config()
    partial_tp_atr=float(config.get("partial_tp_atr",1.5))
    trail_after_partial=bool(config.get("trail_after_partial",True))
    closed=[]; partials=[]; trailed=[]
    for trade in trades:
        ticker=trade["ticker"]; atype=trade.get("asset_type","stock")
        entry=float(trade.get("entry_price",0))
        sl=float(trade.get("sl",0)); tp=float(trade.get("tp",0))
        sig=trade.get("signal","BUY"); side="BUY" if "BUY" in sig else "SELL"
        atr_val=float(trade.get("atr") or entry*0.02)
        partial_taken=bool(trade.get("partial_taken",False))
        original_qty=float(trade.get("original_quantity") or trade.get("quantity") or 0)
        current_qty=float(trade.get("quantity") or original_qty)
        realized_pnl_pct=float(trade.get("realized_pnl_pct",0.0))
        # opened_at → elapsed bars proxy
        try:
            opened=datetime.fromisoformat(trade.get("opened_at","").replace("Z",""))
            elapsed_min=max(0,(datetime.utcnow()-opened).total_seconds()/60)
        except Exception:
            elapsed_min=0
        price=0.0; cached=data_freshness.get_price(ticker)
        if cached and not cached.get("expired"): price=float(cached.get("price",0) or 0)
        if price<=0:
            try:
                end_dt=datetime.utcnow(); start_dt=end_dt-timedelta(days=2); df=await fetch_history(ticker,atype,start_dt.strftime("%Y-%m-%d"),end_dt.strftime("%Y-%m-%d"),"1h")
                if df is not None and len(df): price=float(df["close"].iloc[-1])
            except Exception as e: _log.debug(f"monitor price fetch failed for {ticker}: {e}"); continue
        if price<=0: continue
        hit_sl=price<=sl if side=="BUY" else price>=sl
        hit_tp=price>=tp if side=="BUY" else price<=tp
        if hit_sl or hit_tp:
            pnl_remain=(price-entry)/entry*100 if side=="BUY" else (entry-price)/entry*100
            # qty-weighted: realised partial (50% leg) + remaining leg
            qty_ratio=current_qty/original_qty if original_qty>0 else 1.0
            total_pnl=realized_pnl_pct*(1-qty_ratio)+pnl_remain*qty_ratio
            outcome="WIN" if total_pnl>0 else "LOSS"
            close_reason="TRAIL" if hit_sl and bool(trade.get("trailing_active")) else ("TP" if hit_tp else "SL")
            await trades_col.update_one({"_id":trade["_id"]},{"$set":{"status":"closed","close_price":price,"close_reason":close_reason,"pnl_pct":round(total_pnl,3),"outcome":outcome,"closed_at":datetime.utcnow().isoformat()}})
            closed_trade={**{k:v for k,v in trade.items() if k!="_id"},"close_price":price,"pnl_pct":round(total_pnl,3),"outcome":outcome,"closed_at":datetime.utcnow().isoformat(),"close_reason":close_reason}
            await hist_col.insert_one(closed_trade)
            closed.append({"ticker":ticker,"outcome":outcome,"pnl":round(total_pnl,3),"reason":close_reason})
            # ---- Self-learning loops on real trade outcomes ----
            if config.get("use_bayesian_online",True):
                try:
                    from services.bayesian_online_weights import update_from_trade as _bo_update
                    await _bo_update(closed_trade)
                except Exception as e: _log.debug(f"bayesian online update failed: {e}")
            try:
                from services.weight_engine import update_weights as _we_update
                await _we_update(outcome,sig,trade.get("indicators_at_entry",[]),float(total_pnl),float(trade.get("confidence",50) or 50))
            except Exception as e: _log.debug(f"weight engine update failed: {e}")
            try:
                from services.bayesian_engine import update_likelihoods_from_outcome as _be_update
                await _be_update(trade.get("regime","RANGING"),trade.get("indicators_at_entry",[]),sig,outcome=="WIN")
            except Exception as e: _log.debug(f"bayesian engine update failed: {e}")
            continue
        # ---- Partial take-profit at +Nx ATR ----
        unreal_per_unit=(price-entry) if side=="BUY" else (entry-price)
        partial_trigger=atr_val*partial_tp_atr
        if not partial_taken and atr_val>0 and unreal_per_unit>=partial_trigger:
            half_qty=current_qty/2
            partial_pnl_pct=(price-entry)/entry*100 if side=="BUY" else (entry-price)/entry*100
            new_sl=entry  # move to breakeven after partial
            await trades_col.update_one({"_id":trade["_id"]},{"$set":{"quantity":round(current_qty-half_qty,8),"partial_taken":True,"realized_pnl_pct":round(partial_pnl_pct,3),"sl":round(new_sl,6),"trailing_active":True,"partial_taken_at":datetime.utcnow().isoformat(),"partial_price":price}})
            partials.append({"ticker":ticker,"price":price,"pnl_pct":round(partial_pnl_pct,3)})
            await _alog(f"Partial TP {ticker}: +{partial_pnl_pct:.2f}% (50% closed, SL→BE)","success",partials[-1])
            sl=new_sl; partial_taken=True; current_qty-=half_qty
        # ---- ATR trailing stop (active after partial OR on long-running trades) ----
        if config.get("use_stops",True) and (partial_taken or elapsed_min>15):
            try:
                ts=optimal_trailing_stop(entry,price,atr_val,int(elapsed_min),max(60,int(config.get("max_hold_bars",60))*5),"long" if side=="BUY" else "short")
                new_stop=float(ts.get("optimal_stop",sl))
                improved=(side=="BUY" and new_stop>sl) or (side=="SELL" and new_stop<sl)
                if improved:
                    await trades_col.update_one({"_id":trade["_id"]},{"$set":{"sl":round(new_stop,6),"trailing_active":True}})
                    trailed.append({"ticker":ticker,"old_sl":sl,"new_sl":round(new_stop,6),"price":price})
            except Exception as e:
                _log.debug(f"trail update failed for {ticker}: {e}")
    # ---- Periodic meta-labeller retrain (every N closes) ----
    retrained=None
    if closed and config.get("use_meta_labeler",True):
        try:
            n_since=await hist_col.count_documents({"outcome":{"$in":["WIN","LOSS"]}})
            retrain_every=max(5,int(config.get("meta_labeler_retrain_every",25)))
            if n_since and n_since%retrain_every==0:
                from services.meta_labeler import train_from_history as _ml_train
                retrained=await _ml_train()
                await _alog(f"Meta-labeller retrained: {retrained}","info",retrained)
        except Exception as e: _log.debug(f"meta labeler retrain failed: {e}")
    return {"monitored":len(trades),"closed":len(closed),"partials":len(partials),"trailed":len(trailed),"details":closed,"partial_details":partials,"trail_details":trailed,"meta_labeler_retrain":retrained}
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
