from database import db
from datetime import datetime
col = db["indicator_weights"]
ID  = "current_weights"
DEFAULT = {"RSI":12,"MACD":12,"EMA_CROSS":12,"BOLLINGER":8,"STOCHASTIC":8,"ADX":8,
           "VWAP":8,"OBV":6,"SUPERTREND":8,"ICHIMOKU":6,"VOLUME":6,"ATR_VOLATILITY":6,
           "KALMAN_EMA":8,"FRAMA":6,"ADAPTIVE_RSI":6,"ORDER_FLOW":8,"ENTROPY":4,"HILBERT":4}

async def get_weights():
    doc = await col.find_one({"_id":ID})
    if doc: return {k:v for k,v in doc.items() if k not in ["_id","updated_at","version","update_log","active_strategy"]}
    await col.insert_one({"_id":ID,**DEFAULT,"updated_at":datetime.now().isoformat(),"version":1,"update_log":[]})
    return DEFAULT.copy()

async def update_weights(outcome, signal, indicators, pnl_pct, confidence):
    w = await get_weights()
    doc = await col.find_one({"_id":ID}) or {}
    lr = 0.1*(1+abs(pnl_pct)/5)
    changes = {}
    correct = outcome=="WIN"
    for ind in indicators:
        name = ind.get("indicator","") if isinstance(ind,dict) else str(ind)
        sig  = ind.get("signal","") if isinstance(ind,dict) else ""
        if not name or name not in w or sig in ("NEUTRAL","INFO","ALERT"): continue
        agrees = ("BUY" in sig and "BUY" in signal) or ("SELL" in sig and "SELL" in signal)
        chg = min(lr*(1.0 if agrees else 0.3), 2.0)
        w[name] = min(20, w[name]+chg) if correct else max(1, w[name]-chg)
        changes[name] = round(chg*(1 if correct else -1),3)
    total = sum(w.values())
    if total>0: w = {k:round(v/total*100,2) for k,v in w.items()}
    log = doc.get("update_log",[])
    log.insert(0,{"ts":datetime.now().isoformat(),"outcome":outcome,"pnl":pnl_pct,"changes":changes})
    await col.replace_one({"_id":ID},{"_id":ID,**w,"updated_at":datetime.now().isoformat(),"version":doc.get("version",1)+1,"update_log":log[:100],"active_strategy":doc.get("active_strategy","")},upsert=True)
    return {"status":"updated","changes":changes}
