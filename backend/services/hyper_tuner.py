"""
Hyperparameter Auto-Tuner.
Uses random search to optimize min_confidence, kelly_fraction, SL/TP multipliers.
"""
import numpy as np, asyncio
from datetime import datetime, timedelta
from database import db

tuner_col = db["hyper_tuner"]
signals_col = db["signals_log"]

PARAM_RANGES = {
    "min_confidence":(50, 90),
    "kelly_fraction":(0.25, 0.75),
    "sl_atr_mult":(0.8, 3.0),
    "tp_atr_mult":(1.5, 5.0),
}

def evaluate_params(signals, params):
    """Score parameter combination on historical signals"""
    if not signals: return {"score":0,"trades":0}
    trades = []
    for s in signals:
        if s.get("confidence",0) < params["min_confidence"]: continue
        if not s.get("correct") and not s.get("outcome"): continue
        pnl = s.get("pnl_pct", 0)
        # Apply SL/TP multipliers as proxy: cap losses, cap gains
        if pnl < 0:
            pnl = max(pnl, -params["sl_atr_mult"] * 1.0)
        else:
            pnl = min(pnl, params["tp_atr_mult"] * 1.0)
        trades.append(pnl)
    if len(trades) < 5: return {"score":0,"trades":len(trades)}
    arr = np.array(trades)
    wins = (arr > 0).sum(); total = len(arr)
    win_rate = wins/total
    avg = float(np.mean(arr)); std = float(np.std(arr))
    sharpe = avg/std*np.sqrt(252) if std>0 else 0
    # Apply Kelly fraction as risk multiplier
    final_score = sharpe * params["kelly_fraction"] + win_rate
    return {"score":round(final_score,4),"sharpe":round(sharpe,3),"win_rate":round(win_rate*100,2),"trades":total,"avg_pnl":round(avg,3)}

async def run_tuning(n_trials=40, window_days=60):
    """Random search over parameter space"""
    cutoff = (datetime.now()-timedelta(days=window_days)).isoformat()
    signals = await signals_col.find({"outcome":{"$in":["WIN","LOSS"]},"timestamp":{"$gte":cutoff}}).to_list(3000)
    if len(signals) < 20:
        return {"error":f"Need 20+ resolved signals, have {len(signals)}"}
    best_params = None; best_score = -999; results = []
    for _ in range(n_trials):
        params = {k:float(np.random.uniform(*v)) for k,v in PARAM_RANGES.items()}
        params["min_confidence"] = int(params["min_confidence"])
        score = evaluate_params(signals, params)
        results.append({"params":params,"score":score})
        if score["score"] > best_score:
            best_score = score["score"]; best_params = params
    await tuner_col.replace_one({"_id":"best"},{"_id":"best","params":best_params,
        "score":best_score,"timestamp":datetime.now().isoformat(),"signals_used":len(signals)},upsert=True)
    return {"status":"completed","trials":n_trials,"signals_analyzed":len(signals),
            "best_params":best_params,"best_score":best_score}

async def get_best_params():
    doc = await tuner_col.find_one({"_id":"best"})
    if not doc: return {"available":False,"params":{"min_confidence":70,"kelly_fraction":0.5,"sl_atr_mult":1.5,"tp_atr_mult":3.0}}
    return {"available":True,"params":doc["params"],"score":doc.get("score"),"updated":doc.get("timestamp")}

_tuning_running = False
async def start_tuning_scheduler():
    global _tuning_running
    if _tuning_running: return {"status":"running"}
    _tuning_running = True; asyncio.create_task(_tuning_loop()); return {"status":"started"}
async def _tuning_loop():
    while _tuning_running:
        try: await run_tuning()
        except Exception as e: print(f"[Tuner] {e}")
        await asyncio.sleep(86400 * 7)  # weekly
