"""
TradeAI Auto-Trader v4.3
Connected to: Quant pipeline + Meta Learner + RL Agent + Defensive Mode + Confluence Memory
Self-learning via outcome tracking → updates Q-table, weights, meta-model, and bayesian likelihoods.
"""
import asyncio
from datetime import datetime
from database import db
from services.signal_service import generate_signal
from services.position_sizing import optimal_position
from services.advanced_indicators import optimal_trailing_stop
from services.trade_optimizer import run_optimization
from services.logger import child as _child_log
_log = _child_log('auto_trader')

cfg_col   = db["autotrader_config"]
trades_col= db["open_trades"]
hist_col  = db["trade_history"]
rl_ep_col = db["rl_episodes"]

DEFAULT = {"enabled":False,"paper_mode":True,"min_confidence":70,"max_open":5,"risk_per_trade":2.0,"capital":10000,"timeframe":"swing","scan_interval":300,
           "use_quant":True,"use_stops":True,"use_mtf":True,"use_portfolio_risk":True,
           "use_rl_agent":True,"use_meta_learner":True,"use_defensive":True,
           "watchlist":[{"ticker":"AAPL","type":"stock"},{"ticker":"NVDA","type":"stock"},{"ticker":"TSLA","type":"stock"},{"ticker":"BTC","type":"crypto"},{"ticker":"ETH","type":"crypto"},{"ticker":"SOL","type":"crypto"}]}

async def get_config():
    doc=await cfg_col.find_one({"_id":"config"})
    if not doc: await cfg_col.insert_one({"_id":"config",**DEFAULT}); return DEFAULT.copy()
    doc.pop("_id",None); return {**DEFAULT,**doc}

async def update_config(updates):
    await cfg_col.update_one({"_id":"config"},{"$set":updates},upsert=True)
    return {"status":"updated"}

async def scan_and_execute():
    config=await get_config()
    if not config.get("enabled"): return {"status":"disabled"}

    # ── DEFENSIVE MODE CHECK ──
    defensive_adj = {"halt_trading":False,"size_multiplier":1.0,"min_confidence":config.get("min_confidence",70),"allowed_regimes":None}
    if config.get("use_defensive",True):
        try:
            from services.defensive_mode import check_defensive_mode
            ds = await check_defensive_mode()
            defensive_adj = ds.get("adjustments",defensive_adj)
            if defensive_adj.get("halt_trading"):
                return {"status":"halted_defensive","reason":ds.get("reason","Defensive halt"),"mode":ds.get("mode","HALT")}
        except Exception as _e: _log.debug(f"ignored: {_e}")

    wl=config.get("watchlist",[]); tf=config.get("timeframe","swing")
    min_c=defensive_adj.get("min_confidence",config.get("min_confidence",70))
    size_mult = defensive_adj.get("size_multiplier",1.0)
    allowed_regimes = defensive_adj.get("allowed_regimes")
    capital=config.get("capital",10000)
    max_t=config.get("max_open",5); open_cnt=await trades_col.count_documents({"status":"open"})
    if open_cnt>=max_t: return {"status":"max_trades_reached","open":open_cnt}

    # Get recent P&L for RL state
    from services.defensive_mode import calculate_recent_pnl
    pnl_24h = await calculate_recent_pnl(24)

    executed=[]; rl_decisions=[]
    for item in wl:
        if open_cnt>=max_t: break
        ticker=item["ticker"]; atype=item.get("type","stock")
        if await trades_col.find_one({"ticker":ticker,"status":"open"}): continue
        try: sig=await generate_signal(ticker,atype,tf,use_advanced=True)
        except Exception as e: continue

        if sig.get("confidence",0)<min_c: continue
        if "BUY" not in sig.get("signal","") and "SELL" not in sig.get("signal",""): continue
        regime=sig.get("regime","RANGING")
        if allowed_regimes and regime not in allowed_regimes: continue

        # ── META LEARNER GATE ──
        meta = sig.get("meta_learner",{})
        if config.get("use_meta_learner",True) and meta.get("available"):
            if meta.get("recommend") == "SKIP":
                continue

        # Get historical performance
        history=await hist_col.find({}).sort("closed_at",-1).limit(50).to_list(50)
        wins=[t["pnl_pct"] for t in history if t.get("outcome")=="WIN" and t.get("pnl_pct")]
        losses=[t["pnl_pct"] for t in history if t.get("outcome")=="LOSS" and t.get("pnl_pct")]
        wr=len(wins)/len(history) if history else 0.55
        aw=sum(wins)/len(wins) if wins else 2.0
        al=sum(losses)/len(losses) if losses else -1.5
        trade_ret=[t.get("pnl_pct",0) for t in history]
        eq=[capital]; r=capital
        for t in history: r=r*(1+t.get("pnl_pct",0)/100); eq.append(r)

        # ── RL AGENT DECISION ──
        rl_size_mult = 1.0; rl_state_key = None; rl_action_idx = None
        if config.get("use_rl_agent",True):
            try:
                from services.rl_agent import get_action
                atr_pct = sig.get("atr",0)/float(sig.get("price",1))*100 if sig.get("price") else 1.0
                rl_decision = await get_action(regime, sig["confidence"], atr_pct, pnl_24h["total_pnl"], open_cnt, epsilon=0.05)
                rl_decisions.append({"ticker":ticker,"action":rl_decision["action"]})
                if rl_decision["action"] == "SKIP":
                    continue
                rl_size_mult = rl_decision["size_multiplier"]
                rl_state_key = rl_decision["state_key"]
                rl_action_idx = rl_decision["action_idx"]
            except Exception as e: _log.debug(f"ignored: {e}")

        # Quant sizing (Kelly + Monte Carlo)
        if config.get("use_quant",True):
            try:
                opt=await optimal_position(ticker,atype,sig["signal"],capital,wr,aw,al,regime,trade_ret,eq)
                pos_pct=opt["recommended_pct"]
            except: pos_pct=config.get("risk_per_trade",2.0)
        else: pos_pct=config.get("risk_per_trade",2.0)

        # Apply RL + defensive multipliers
        pos_pct = pos_pct * rl_size_mult * size_mult

        # MTF + portfolio risk
        if config.get("use_mtf",True):
            open_pos=await trades_col.find({"status":"open"}).to_list(50)
            try:
                import pandas as pd
                opt_r=await run_optimization(ticker,atype,sig["signal"],sig["confidence"],pd.Series([float(sig["price"])]*50),regime,[{"risk_pct":pos_pct}]*len(open_pos),pos_pct)
                if not opt_r.get("approved"): continue
                pos_pct=opt_r.get("adjusted_risk_pct",pos_pct); final_sig=opt_r.get("final_signal",sig["signal"]); final_conf=opt_r.get("final_confidence",sig["confidence"])
            except: final_sig=sig["signal"]; final_conf=sig["confidence"]
        else: final_sig=sig["signal"]; final_conf=sig["confidence"]

        entry=float(sig["price"]); qty=capital*(pos_pct/100)/entry if entry>0 else 0; atr_val=sig.get("atr",entry*0.02)
        if config.get("use_stops",True):
            sc=optimal_trailing_stop(entry,entry,atr_val,0,200,"long" if "BUY" in final_sig else "short")
            sl=sc["optimal_stop"]
        else: sl=sig.get("sl",entry*(0.97 if "BUY" in final_sig else 1.03))
        tp=sig.get("tp",entry*(1.06 if "BUY" in final_sig else 0.94))

        trade={"ticker":ticker,"asset_type":atype,"signal":final_sig,"confidence":final_conf,
               "entry_price":entry,"quantity":round(qty,6),"position_value":round(capital*pos_pct/100,2),
               "position_pct":round(pos_pct,2),"sl":round(sl,4),"tp":round(tp,4),"atr":round(atr_val,4),
               "regime":regime,"timeframe":tf,"status":"open","paper_mode":config.get("paper_mode",True),
               "opened_at":datetime.now().isoformat(),
               "quant_powered":config.get("use_quant",True),
               "rl_state":rl_state_key,"rl_action":rl_action_idx,"rl_size_mult":rl_size_mult,
               "meta_p_win":meta.get("p_win",None),
               "indicators_at_entry":sig.get("indicators",[]),
               "enhancements_at_entry":sig.get("enhancements",{}),
               "entropy_tradeable":next((i.get("tradeable",True) for i in sig.get("indicators",[]) if i.get("indicator")=="ENTROPY"),True)}

        await trades_col.insert_one(trade)
        executed.append({"ticker":ticker,"signal":final_sig,"entry":entry,"size":round(pos_pct,2),"rl_action":rl_decisions[-1]["action"] if rl_decisions else "DIRECT"})
        open_cnt+=1

        if not config.get("paper_mode",True):
            try:
                from services.alert_service import send_telegram
                await send_telegram(f"🤖 <b>Auto-Trade</b>\n{final_sig} {ticker} ${entry} Size={pos_pct:.1f}% SL={sl:.4f} TP={tp:.4f}\nRL: {rl_decisions[-1]['action'] if rl_decisions else 'N/A'}\nMeta P(win): {meta.get('p_win','N/A')}")
            except Exception as _e: _log.debug(f"ignored: {_e}")

    return {"status":"scanned","executed":len(executed),"trades":executed,"rl_decisions":rl_decisions,
            "defensive_mode":defensive_adj}

async def monitor_open():
    trades=await trades_col.find({"status":"open"}).to_list(100)
    if not trades: return {"monitored":0}
    import yfinance as yf, ccxt
    closed=[]
    for trade in trades:
        ticker=trade["ticker"]; atype=trade.get("asset_type","stock")
        entry=float(trade.get("entry_price",0)); sl=float(trade.get("sl",0)); tp=float(trade.get("tp",0))
        sig=trade.get("signal","BUY")
        try:
            loop=asyncio.get_event_loop()
            if atype=="stock":
                price=float(await loop.run_in_executor(None,lambda: yf.Ticker(ticker).info.get("regularMarketPrice",0)))
            else:
                price=float((await loop.run_in_executor(None,lambda: ccxt.binance().fetch_ticker(f"{ticker}/USDT"))).get("last",0))
        except: continue
        if price<=0: continue

        hit_sl=price<=sl if "BUY" in sig else price>=sl
        hit_tp=price>=tp if "BUY" in sig else price<=tp

        if hit_sl or hit_tp:
            pnl=(price-entry)/entry*100 if "BUY" in sig else (entry-price)/entry*100
            outcome="WIN" if hit_tp else "LOSS"
            close_reason="TP" if hit_tp else "SL"
            await trades_col.update_one({"_id":trade["_id"]},{"$set":{"status":"closed","close_price":price,
                "close_reason":close_reason,"pnl_pct":round(pnl,3),"outcome":outcome,"closed_at":datetime.now().isoformat()}})

            history_record={**{k:v for k,v in trade.items() if k!="_id"},"close_price":price,
                "pnl_pct":round(pnl,3),"outcome":outcome,"closed_at":datetime.now().isoformat()}
            await hist_col.insert_one(history_record)
            closed.append({"ticker":ticker,"outcome":outcome,"pnl":round(pnl,3)})

            # ── SELF-LEARNING UPDATES ──
            # 1. RL Q-table update
            if trade.get("rl_state") and trade.get("rl_action") is not None:
                try:
                    from services.rl_agent import update_q
                    reward = pnl / 10 if outcome=="WIN" else pnl / 5  # penalize losses heavier
                    await update_q(trade["rl_state"], int(trade["rl_action"]), reward)
                except Exception as e: print(f"[RL update] {e}")

            # 2. Confluence Memory record
            try:
                from services.confluence_memory import record_outcome
                await record_outcome(
                    trade.get("indicators_at_entry",[]),
                    trade.get("regime","RANGING"),
                    trade.get("entropy_tradeable",True),
                    trade.get("signal","BUY"),
                    outcome, round(pnl,3)
                )
            except Exception as e: print(f"[ConfMem] {e}")

            # 3. Weight engine update
            try:
                from services.weight_engine import update_weights
                await update_weights(outcome, trade.get("signal","BUY"),
                                     trade.get("indicators_at_entry",[]),
                                     round(pnl,3), trade.get("confidence",50))
            except Exception as e: print(f"[Weights] {e}")

            # 4. Bayesian likelihoods update
            try:
                from services.bayesian_engine import update_likelihoods_from_outcome
                await update_likelihoods_from_outcome(
                    trade.get("regime","RANGING"),
                    trade.get("indicators_at_entry",[]),
                    trade.get("signal","BUY"),
                    outcome == "WIN"
                )
            except Exception as e: _log.debug(f"ignored: {e}")  # may not exist

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
        except Exception as e: print(f"[AT] {e}")
        config=await get_config(); await asyncio.sleep(config.get("scan_interval",300))
