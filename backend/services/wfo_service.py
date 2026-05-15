"""
Walk-Forward Optimizer
Tests weight combinations on historical signals, applies best to live trading.
"""
import asyncio, numpy as np, itertools
from datetime import datetime, timedelta
from database import db
from services.weight_engine import get_weights, col as wcol, ID as WID, DEFAULT as WDEF

wfo_col = db["wfo_history"]
signals_col = db["signals_log"]

def score_weights_on_signals(signals, weights):
    """Simulate signal accuracy given a weight set"""
    if not signals: return {"win_rate":0,"trades":0,"sharpe":0}
    wins = 0; losses = 0; returns = []
    for s in signals:
        score = 0; max_score = 0
        for ind in s.get("indicators",[]):
            if not isinstance(ind,dict): continue
            name = ind.get("indicator","")
            ind_score = ind.get("score",0)
            w = weights.get(name, 5)
            score += ind_score * w
            max_score += 2 * w
        if max_score == 0: continue
        norm = score/max_score
        # Decision: BUY if norm > 0.25, SELL if < -0.25
        predicted_buy = norm > 0.25
        predicted_sell = norm < -0.25
        if not (predicted_buy or predicted_sell): continue
        actual_correct = s.get("correct", False)
        # Did we predict in same direction as actual signal that turned out correct?
        actual_buy = "BUY" in s.get("signal","")
        if (predicted_buy and actual_buy) or (predicted_sell and not actual_buy):
            # We agree with original signal
            if actual_correct:
                wins += 1; returns.append(s.get("pnl_pct",1.0))
            else:
                losses += 1; returns.append(s.get("pnl_pct",-1.0))
    total = wins + losses
    if total == 0: return {"win_rate":0,"trades":0,"sharpe":0,"avg_return":0}
    win_rate = wins/total
    avg_ret = float(np.mean(returns)) if returns else 0
    std_ret = float(np.std(returns)) if len(returns)>1 else 1
    sharpe = avg_ret/std_ret * np.sqrt(252) if std_ret>0 else 0
    return {"win_rate":round(win_rate*100,2),"trades":total,"wins":wins,"losses":losses,
            "avg_return":round(avg_ret,3),"sharpe":round(sharpe,3)}

async def run_wfo(window_days=90, n_candidates=30):
    """Test random weight combinations on last N days of signals"""
    cutoff = (datetime.now()-timedelta(days=window_days)).isoformat()
    signals = await signals_col.find({"outcome":{"$in":["WIN","LOSS"]},"timestamp":{"$gte":cutoff}}).to_list(3000)
    if len(signals) < 30:
        return {"error":f"Not enough resolved signals: {len(signals)}/30 minimum"}
    base = WDEF.copy()
    candidates = [base.copy()]
    # Generate variations
    for _ in range(n_candidates-1):
        c = base.copy()
        for k in list(c.keys()):
            c[k] = max(1, min(20, c[k] + np.random.uniform(-4, 4)))
        total = sum(c.values())
        if total > 0: c = {k:round(v/total*100,2) for k,v in c.items()}
        candidates.append(c)
    # Evaluate each
    results = []
    for i,w in enumerate(candidates):
        score = score_weights_on_signals(signals, w)
        results.append({"weights":w,"score":score,"composite":score["sharpe"]+score["win_rate"]/100})
    results.sort(key=lambda x:x["composite"],reverse=True)
    best = results[0]
    await wfo_col.insert_one({"timestamp":datetime.now().isoformat(),"window_days":window_days,
        "candidates":n_candidates,"signals_used":len(signals),"best_weights":best["weights"],
        "best_score":best["score"],"baseline_score":results[-1]["score"]})
    # Apply best if significantly better than current
    current_score = score_weights_on_signals(signals, await get_weights())
    if best["score"]["sharpe"] > current_score["sharpe"] * 1.1:
        log = (await wcol.find_one({"_id":WID}) or {}).get("update_log",[])
        log.insert(0,{"ts":datetime.now().isoformat(),"source":"wfo_optimizer","sharpe_gain":best["score"]["sharpe"]-current_score["sharpe"]})
        await wcol.replace_one({"_id":WID},{"_id":WID,**best["weights"],"updated_at":datetime.now().isoformat(),"update_log":log[:100],"version":(await wcol.find_one({"_id":WID}) or {}).get("version",0)+1,"active_strategy":"wfo_optimized"},upsert=True)
        applied = True
    else:
        applied = False
    return {"status":"completed","signals_analyzed":len(signals),"candidates_tested":len(candidates),
        "best_score":best["score"],"current_score":current_score,"applied":applied,"best_weights":best["weights"]}

async def get_wfo_history(limit=20):
    docs = await wfo_col.find({}).sort("timestamp",-1).limit(limit).to_list(limit)
    for d in docs: d["_id"]=str(d["_id"])
    return docs

_wfo_running = False
async def start_wfo_scheduler():
    global _wfo_running
    if _wfo_running: return {"status":"running"}
    _wfo_running = True
    asyncio.create_task(_wfo_loop()); return {"status":"started"}
async def _wfo_loop():
    while _wfo_running:
        try: await run_wfo()
        except Exception as e: print(f"[WFO] {e}")
        await asyncio.sleep(86400 * 7)  # weekly
