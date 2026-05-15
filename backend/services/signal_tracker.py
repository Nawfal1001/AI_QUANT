"""
Signal Performance Tracker.

Logs every emitted signal with metadata.
After the signal resolves (TP/SL/timeout), updates win rate stats grouped by:
- strategy
- symbol (ticker)
- timeframe
- regime

Used by signal_resolver to auto-adjust strategy weights based on rolling performance.
"""
from datetime import datetime
from typing import Optional

from database import db
from services.logger import child

log = child("signal_tracker")

col_signals = db["signal_log"]
col_stats = db["signal_stats"]


async def log_signal(
    user_id: str,
    ticker: str,
    signal: str,
    confidence: float,
    strategy: str = "default",
    timeframe: str = "swing",
    regime: str = "unknown",
    asset_type: str = "stock",
    metadata: dict = None,
) -> str:
    """Log an emitted signal. Returns signal_id used to resolve it later."""
    doc = {
        "user_id": user_id,
        "ticker": ticker.upper(),
        "asset_type": asset_type,
        "signal": signal,
        "confidence": float(confidence),
        "strategy": strategy,
        "timeframe": timeframe,
        "regime": regime,
        "metadata": metadata or {},
        "status": "pending",
        "emitted_at": datetime.utcnow().isoformat(),
    }
    r = await col_signals.insert_one(doc)
    return str(r.inserted_id)


async def resolve_signal(signal_id: str, outcome: str, pnl_pct: float = 0) -> dict:
    """
    Mark a signal as resolved.
    outcome: 'win' | 'loss' | 'expired'
    Updates aggregate stats by (strategy, symbol, timeframe, regime).
    """
    from bson import ObjectId
    try:
        oid = ObjectId(signal_id)
    except Exception:
        return {"error": "Invalid signal_id"}

    sig = await col_signals.find_one({"_id": oid})
    if not sig:
        return {"error": "Signal not found"}
    if sig.get("status") != "pending":
        return {"error": "Already resolved"}

    await col_signals.update_one(
        {"_id": oid},
        {"$set": {
            "status": "resolved",
            "outcome": outcome,
            "pnl_pct": float(pnl_pct),
            "resolved_at": datetime.utcnow().isoformat(),
        }},
    )

    # Update stats — bucketed by (user, strategy, ticker, timeframe, regime)
    bucket = {
        "user_id": sig["user_id"],
        "strategy": sig.get("strategy", "default"),
        "ticker": sig["ticker"],
        "timeframe": sig.get("timeframe", "swing"),
        "regime": sig.get("regime", "unknown"),
    }
    inc = {"total": 1, "pnl_sum": float(pnl_pct)}
    if outcome == "win":
        inc["wins"] = 1
    elif outcome == "loss":
        inc["losses"] = 1
    else:
        inc["expired"] = 1
    await col_stats.update_one(bucket, {"$inc": inc, "$set": {"updated_at": datetime.utcnow().isoformat()}}, upsert=True)

    log.info(f"resolved signal {signal_id} as {outcome} (pnl {pnl_pct:.2f}%)")
    return {"status": "resolved", "outcome": outcome}


async def get_stats(user_id: str, group_by: str = "strategy") -> list:
    """
    Returns aggregated stats grouped by one of: strategy, ticker, timeframe, regime.
    Each row: {key, total, wins, losses, win_rate, avg_pnl_pct}
    """
    valid = ["strategy", "ticker", "timeframe", "regime"]
    if group_by not in valid:
        return [{"error": f"group_by must be one of {valid}"}]

    pipeline = [
        {"$match": {"user_id": user_id}},
        {"$group": {
            "_id": f"${group_by}",
            "total": {"$sum": "$total"},
            "wins": {"$sum": {"$ifNull": ["$wins", 0]}},
            "losses": {"$sum": {"$ifNull": ["$losses", 0]}},
            "expired": {"$sum": {"$ifNull": ["$expired", 0]}},
            "pnl_sum": {"$sum": "$pnl_sum"},
        }},
        {"$sort": {"total": -1}},
    ]
    out = []
    async for row in col_stats.aggregate(pipeline):
        total = row["total"] or 1
        wins = row.get("wins", 0) or 0
        out.append({
            "key": row["_id"],
            "total": total,
            "wins": wins,
            "losses": row.get("losses", 0) or 0,
            "expired": row.get("expired", 0) or 0,
            "win_rate": round(wins / total * 100, 2),
            "avg_pnl_pct": round(row.get("pnl_sum", 0) / total, 3),
        })
    return out


async def get_strategy_weights(user_id: str) -> dict:
    """
    Returns a dict {strategy: weight} where weight is proportional to rolling win rate
    above 50%. Used by signal_service to dampen losing strategies.
    """
    stats = await get_stats(user_id, "strategy")
    weights = {}
    for s in stats:
        if s.get("total", 0) < 5:
            weights[s["key"]] = 1.0  # not enough data
            continue
        wr = s["win_rate"] / 100
        # Weight = 0.5 to 1.5 range based on win rate
        # 50% -> 1.0, 70% -> 1.4, 30% -> 0.6
        weights[s["key"]] = round(max(0.3, min(1.5, 0.5 + wr)), 2)
    return weights


async def recent_signals(user_id: str, limit: int = 50) -> list:
    docs = await col_signals.find({"user_id": user_id}).sort("emitted_at", -1).limit(limit).to_list(limit)
    for d in docs:
        d["_id"] = str(d["_id"])
    return docs
