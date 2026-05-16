"""
Signal Resolver with full self-learning loop:
- Updates weights
- Updates Bayesian likelihoods
- Updates Confluence Memory
- Trains Meta Learner periodically
"""
import asyncio, yfinance as yf, ccxt
from datetime import datetime, timedelta
from database import db
scol=db["signals_log"]
DELAYS={"scalping":0.5,"intraday":8,"swing":48,"position":168}
MIN_MOVE={"scalping":0.3,"intraday":0.5,"swing":1.0,"position":2.0}

def _price(ticker,atype):
    try:
        if atype=="stock": return float(yf.Ticker(ticker).info.get("regularMarketPrice",0))
        return float(ccxt.binance().fetch_ticker(f"{ticker}/USDT").get("last",0))
    except Exception as e:
        print(f"[Resolver] price fetch failed for {ticker}: {e}")
        return 0.0

async def resolve_one(s):
    ticker=s.get("ticker",""); atype=s.get("asset_type","stock"); tf=s.get("timeframe","swing")
    sig=s.get("signal",""); entry=float(s.get("price",0))
    if not entry or not sig or sig=="HOLD": return {"resolved":False}
    try: st=datetime.fromisoformat(s.get("timestamp",""))
    except Exception: return {"resolved":False}
    if datetime.utcnow()<st+timedelta(hours=DELAYS.get(tf,48)): return {"resolved":False,"reason":"Too early"}
    loop=asyncio.get_event_loop(); price=await loop.run_in_executor(None,_price,ticker,atype)
    if price<=0: return {"resolved":False}
    move=(price-entry)/entry*100; min_m=MIN_MOVE.get(tf,1.0); is_buy="BUY" in sig
    if is_buy:
        if move>=min_m: correct=True
        elif move<=-min_m: correct=False
        else: return {"resolved":False,"reason":f"Pending {move:.2f}%"}
    else:
        if move<=-min_m: correct=True
        elif move>=min_m: correct=False
        else: return {"resolved":False,"reason":f"Pending {move:.2f}%"}
    outcome="WIN" if correct else "LOSS"; pnl=abs(move) if correct else -abs(move)
    await scol.update_one({"_id":s["_id"]},{"$set":{"outcome":outcome,"outcome_price":price,
        "outcome_date":datetime.utcnow().isoformat(),"correct":correct,"pnl_pct":round(pnl,3)}})

    # SELF-LEARNING LOOPS
    if s.get("indicators"):
        # 1. Weight engine
        try:
            from services.weight_engine import update_weights
            await update_weights(outcome,sig,s["indicators"],round(pnl,3),s.get("confidence",50))
        except Exception as e: print(f"[Weights] {e}")
        # 2. Bayesian likelihoods
        try:
            from services.bayesian_engine import update_likelihoods_from_outcome
            await update_likelihoods_from_outcome(s.get("regime","RANGING"),s["indicators"],sig,correct)
        except Exception as e: print(f"[Bayes] {e}")
        # 3. Confluence memory
        try:
            from services.confluence_memory import record_outcome
            entropy_ok = next((i.get("tradeable",True) for i in s["indicators"] if i.get("indicator")=="ENTROPY"),True)
            await record_outcome(s["indicators"],s.get("regime","RANGING"),entropy_ok,sig,outcome,round(pnl,3))
        except Exception as e: print(f"[ConfMem] {e}")

    return {"resolved":True,"outcome":outcome,"ticker":ticker,"pnl_pct":round(pnl,3)}

async def run_resolver():
    pending=await scol.find({"outcome":None,"signal":{"$nin":["HOLD","UNKNOWN"]}}).to_list(500)
    res=0; still=0
    for s in pending:
        try:
            r=await resolve_one(s)
            if r["resolved"]: res+=1
            else: still+=1
        except Exception as e: still+=1; print(f"[Resolver] {e}")
        await asyncio.sleep(0.2)
    # If we resolved enough signals, retrain meta-learner
    if res >= 5:
        try:
            from services.meta_learner import train_meta_learner
            await train_meta_learner(min_samples=50)
            print(f"[MetaLearner] Retrained after {res} resolutions")
        except Exception as e: print(f"[MetaTrain] {e}")
    return {"checked":len(pending),"resolved":res,"still_pending":still}

_running=False
async def start_resolver():
    global _running
    if _running: return {"status":"running"}
    _running=True; asyncio.create_task(_resolver_loop()); return {"status":"started"}
async def stop_resolver():
    global _running; _running=False; return {"status":"stopped"}
async def _resolver_loop():
    while _running:
        try: await run_resolver()
        except Exception as e: print(f"[Resolver] {e}")
        await asyncio.sleep(900)

async def resolver_stats():
    total=await scol.count_documents({}); resolved=await scol.count_documents({"outcome":{"$ne":None}})
    wins=await scol.count_documents({"outcome":"WIN"}); losses=await scol.count_documents({"outcome":"LOSS"})
    pending=await scol.count_documents({"outcome":None,"signal":{"$nin":["HOLD"]}})
    return {"total":total,"resolved":resolved,"wins":wins,"losses":losses,"pending":pending,
            "win_rate":round(wins/max(resolved,1)*100,1),"running":_running}
