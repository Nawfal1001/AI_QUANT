"""
Signal Confluence Memory
Stores every signal+outcome, queries historical accuracy for similar setups.
"""
from database import db
from datetime import datetime, timedelta
import hashlib, json

mem_col = db["confluence_memory"]
signals_col = db["signals_log"]

def signal_signature(indicators, regime, entropy_tradeable=True):
    """Generate a hash signature for a signal setup"""
    buckets = []
    for ind in (indicators or []):
        if not isinstance(ind, dict): continue
        name = ind.get("indicator","")
        sig = ind.get("signal","NEUTRAL")
        if sig in ("BUY","STRONG BUY"): buckets.append(f"{name}:B")
        elif sig in ("SELL","STRONG SELL"): buckets.append(f"{name}:S")
        elif sig == "WEAK BUY": buckets.append(f"{name}:wB")
        elif sig == "WEAK SELL": buckets.append(f"{name}:wS")
    buckets.sort()
    sig_string = f"{regime}|{'|'.join(buckets)}|E{int(entropy_tradeable)}"
    return hashlib.md5(sig_string.encode()).hexdigest()[:12], sig_string

async def get_historical_accuracy(indicators, regime, entropy_tradeable=True, min_samples=5):
    """Look up similar past setups and return historical win rate"""
    sig_hash, sig_string = signal_signature(indicators, regime, entropy_tradeable)
    doc = await mem_col.find_one({"signature": sig_hash})
    if not doc or doc.get("total",0) < min_samples:
        return {"signature": sig_hash, "samples": doc.get("total",0) if doc else 0,
                "win_rate": None, "confidence_boost": 0, "has_history": False}
    total = doc["total"]; wins = doc.get("wins",0)
    win_rate = wins / total
    # Boost confidence if historical win rate is high
    if win_rate >= 0.70 and total >= 10:
        boost = +15
    elif win_rate >= 0.60 and total >= 10:
        boost = +8
    elif win_rate <= 0.30 and total >= 10:
        boost = -20
    elif win_rate <= 0.40 and total >= 10:
        boost = -10
    else:
        boost = 0
    return {"signature": sig_hash, "samples": total, "wins": wins,
            "win_rate": round(win_rate*100,1), "confidence_boost": boost,
            "has_history": True, "avg_pnl": doc.get("avg_pnl",0)}

async def record_outcome(indicators, regime, entropy_tradeable, signal, outcome, pnl_pct):
    """Record a resolved signal outcome into memory"""
    sig_hash, sig_string = signal_signature(indicators, regime, entropy_tradeable)
    is_win = outcome == "WIN"
    doc = await mem_col.find_one({"signature": sig_hash})
    if not doc:
        await mem_col.insert_one({
            "signature": sig_hash, "description": sig_string,
            "total": 1, "wins": 1 if is_win else 0, "losses": 0 if is_win else 1,
            "pnl_sum": pnl_pct, "avg_pnl": pnl_pct,
            "regime": regime, "first_seen": datetime.now().isoformat(),
            "last_seen": datetime.now().isoformat(),
        })
    else:
        total = doc["total"]+1; wins = doc.get("wins",0)+(1 if is_win else 0)
        losses = doc.get("losses",0)+(0 if is_win else 1)
        pnl_sum = doc.get("pnl_sum",0)+pnl_pct
        await mem_col.update_one({"signature":sig_hash},{"$set":{
            "total":total,"wins":wins,"losses":losses,"pnl_sum":pnl_sum,
            "avg_pnl":round(pnl_sum/total,3),"last_seen":datetime.now().isoformat()
        }})
    return {"recorded":True,"signature":sig_hash}

async def get_top_setups(limit=20, min_samples=10):
    """Get the highest-performing historical setups"""
    docs = await mem_col.find({"total":{"$gte":min_samples}}).to_list(1000)
    for d in docs:
        d["_id"]=str(d["_id"])
        d["win_rate"]=round(d.get("wins",0)/max(d["total"],1)*100,1)
    docs.sort(key=lambda x:x["win_rate"],reverse=True)
    return docs[:limit]

async def get_memory_stats():
    total = await mem_col.count_documents({})
    high_conf = await mem_col.count_documents({"total":{"$gte":10}})
    return {"total_setups":total,"setups_with_history":high_conf}
