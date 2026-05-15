"""
User strategy storage layer.

Each strategy is scoped to a user_id. Saved in MongoDB collection 'user_strategies'.
"""
from datetime import datetime
from typing import Optional

from database import db
from services.custom_strategy import validate_strategy, run_custom_strategy
from services.logger import child

log = child("user_strategies")
col = db["user_strategies"]


async def list_user_strategies(user_id: str) -> list:
    docs = await col.find({"user_id": user_id}).sort("updated_at", -1).to_list(100)
    for d in docs:
        d["_id"] = str(d["_id"])
    return docs


async def get_user_strategy(user_id: str, strategy_id: str) -> Optional[dict]:
    from bson import ObjectId
    try:
        oid = ObjectId(strategy_id)
    except Exception:
        return None
    doc = await col.find_one({"_id": oid, "user_id": user_id})
    if doc:
        doc["_id"] = str(doc["_id"])
    return doc


async def save_user_strategy(user_id: str, data: dict) -> dict:
    """Validate + insert/update. Returns the saved doc or {'error': ...}."""
    v = validate_strategy(data)
    if not v["ok"]:
        return {"error": v["error"]}

    now = datetime.utcnow().isoformat()
    strategy_id = data.get("id")
    doc = {
        "user_id": user_id,
        "name": data["name"].strip(),
        "description": data.get("description", "").strip()[:240],
        "rules": data["rules"],
        "min_confidence": int(data.get("min_confidence", 50)),
        "updated_at": now,
    }

    if strategy_id:
        from bson import ObjectId
        try:
            oid = ObjectId(strategy_id)
        except Exception:
            return {"error": "Invalid strategy id"}
        existing = await col.find_one({"_id": oid, "user_id": user_id})
        if not existing:
            return {"error": "Strategy not found"}
        await col.update_one({"_id": oid, "user_id": user_id}, {"$set": doc})
        doc["_id"] = strategy_id
        doc["created_at"] = existing.get("created_at", now)
        log.info(f"user {user_id} updated strategy '{doc['name']}' ({strategy_id})")
        return doc

    doc["created_at"] = now
    r = await col.insert_one(doc)
    doc["_id"] = str(r.inserted_id)
    log.info(f"user {user_id} created strategy '{doc['name']}' ({doc['_id']})")
    return doc


async def delete_user_strategy(user_id: str, strategy_id: str) -> dict:
    from bson import ObjectId
    try:
        oid = ObjectId(strategy_id)
    except Exception:
        return {"error": "Invalid strategy id"}
    res = await col.delete_one({"_id": oid, "user_id": user_id})
    return {"deleted": res.deleted_count}


async def test_user_strategy(strategy: dict, ticker: str, asset_type: str, days: int) -> dict:
    """
    Validate then dry-run on recent historical data.
    Returns the latest-bar signal + sample rule firings across the history.
    """
    v = validate_strategy(strategy)
    if not v["ok"]:
        return {"error": v["error"]}

    from datetime import timedelta
    from services.backtest_engine import fetch_history
    end = datetime.utcnow().strftime("%Y-%m-%d")
    start = (datetime.utcnow() - timedelta(days=days)).strftime("%Y-%m-%d")
    df = await fetch_history(ticker.upper(), asset_type, start, end, "1d")
    if df is None or len(df) < 30:
        return {"error": f"Insufficient history for {ticker}"}

    # Latest signal
    latest = run_custom_strategy(strategy, df.iloc[-50:])

    # Count fires per rule over the last 90 bars (or fewer)
    sample_size = min(90, len(df) - 30)
    rule_counts = [0] * len(strategy["rules"])
    signal_counts = {"BUY": 0, "SELL": 0, "STRONG_BUY": 0, "STRONG_SELL": 0, "HOLD": 0}
    for i in range(len(df) - sample_size, len(df)):
        window = df.iloc[max(0, i - 50):i + 1]
        result = run_custom_strategy(strategy, window)
        signal_counts[result["signal"]] = signal_counts.get(result["signal"], 0) + 1
        for r_idx, rule in enumerate(strategy["rules"]):
            if rule["when"] in (result.get("rules_fired") or []):
                rule_counts[r_idx] += 1

    return {
        "latest": latest,
        "signal_distribution": signal_counts,
        "rule_fire_counts": [
            {"rule": strategy["rules"][i]["when"], "fires": rule_counts[i], "side": strategy["rules"][i]["side"]}
            for i in range(len(strategy["rules"]))
        ],
        "bars_tested": sample_size,
        "actionable_signals": signal_counts.get("BUY", 0) + signal_counts.get("STRONG_BUY", 0)
                              + signal_counts.get("SELL", 0) + signal_counts.get("STRONG_SELL", 0),
    }
