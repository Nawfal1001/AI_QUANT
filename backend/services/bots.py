"""
Autonomous Trading Bots.

A bot is a user-defined recipe that combines:
  - A strategy (built-in like "ensemble" OR a user-defined strategy from Strategy Lab)
  - A watchlist (tickers to monitor)
  - A schedule (how often to scan)
  - A broker (paper, alpaca, binance, ...)
  - Sizing rules (% of equity per trade)

The bot_runner background service iterates every user's enabled bots on schedule,
generates signals, and submits orders through the order router.

DB collections (user-scoped):
- bots             : bot definitions
- bot_executions   : log of every signal evaluation a bot has done
- bot_trades       : trades opened by a bot (linked back to bot_id)
"""
from datetime import datetime
from typing import Optional

from bson import ObjectId

from database import db
from services.logger import child

log = child("bots")

col_bots = db["bots"]
col_executions = db["bot_executions"]


# Bot schedule options — how often the runner evaluates the bot
SCHEDULES = {
    "1m": 60,
    "5m": 300,
    "15m": 900,
    "30m": 1800,
    "1h": 3600,
    "4h": 14400,
    "1d": 86400,
}


# Sizing modes — how much capital to allocate per trade
SIZING_MODES = ["fixed_pct", "kelly", "atr_volatility"]


def _validate_definition(data: dict) -> Optional[str]:
    """Validate a bot definition. Returns None if OK, error string otherwise."""
    if not data.get("name") or not isinstance(data["name"], str) or len(data["name"].strip()) == 0:
        return "name is required"
    if len(data["name"]) > 60:
        return "name too long (max 60 chars)"

    strategy_type = data.get("strategy_type", "builtin")
    if strategy_type not in ("builtin", "user"):
        return "strategy_type must be 'builtin' or 'user'"

    if not data.get("strategy_id"):
        return "strategy_id is required"

    watchlist = data.get("watchlist", [])
    if not isinstance(watchlist, list) or len(watchlist) == 0:
        return "watchlist must be a non-empty list"
    if len(watchlist) > 20:
        return "watchlist max 20 tickers"
    for item in watchlist:
        if not isinstance(item, dict) or "ticker" not in item:
            return "watchlist items must be {ticker, asset_type}"
        if item.get("asset_type") not in ("stock", "crypto", "forex", "oil", "gold", "macro"):
            return "asset_type must be one of stock | crypto | forex | oil | gold | macro"

    if data.get("schedule") not in SCHEDULES:
        return f"schedule must be one of {list(SCHEDULES.keys())}"

    if data.get("broker") not in ("paper", "alpaca", "binance", "oanda"):
        return "broker must be paper / alpaca / binance / oanda"

    sizing_mode = data.get("sizing_mode", "fixed_pct")
    if sizing_mode not in SIZING_MODES:
        return f"sizing_mode must be one of {SIZING_MODES}"

    try:
        sizing_pct = float(data.get("sizing_pct", 1.0))
    except (ValueError, TypeError):
        return "sizing_pct must be numeric"
    if sizing_pct <= 0 or sizing_pct > 50:
        return "sizing_pct must be in (0, 50]"

    try:
        min_conf = int(data.get("min_confidence", 60))
    except (ValueError, TypeError):
        return "min_confidence must be an integer"
    if not 0 <= min_conf <= 100:
        return "min_confidence must be in [0, 100]"

    return None


async def list_bots(user_id: str) -> list:
    docs = await col_bots.find({"user_id": user_id}).sort("created_at", -1).to_list(100)
    for d in docs:
        d["_id"] = str(d["_id"])
    return docs


async def get_bot(user_id: str, bot_id: str) -> Optional[dict]:
    try:
        oid = ObjectId(bot_id)
    except Exception:
        return None
    doc = await col_bots.find_one({"_id": oid, "user_id": user_id})
    if doc:
        doc["_id"] = str(doc["_id"])
    return doc


async def create_bot(user_id: str, data: dict) -> dict:
    """Validate + insert a new bot. Disabled by default."""
    err = _validate_definition(data)
    if err:
        return {"error": err}

    # If strategy_type='user', verify the strategy exists and belongs to the user
    if data["strategy_type"] == "user":
        try:
            oid = ObjectId(data["strategy_id"])
        except Exception:
            return {"error": "invalid strategy_id"}
        strat = await db["user_strategies"].find_one({"_id": oid, "user_id": user_id})
        if not strat:
            return {"error": "user strategy not found"}

    # Risk-limits gate: a bot can be created disabled at any time, but it can only be
    # enabled after risk limits are set (enforced at update time).
    enabled = bool(data.get("enabled", False))
    if enabled:
        from services import risk_engine
        if not await risk_engine.is_configured(user_id):
            return {"error": "Risk limits not configured. Set them in Settings before enabling a bot."}

    now = datetime.utcnow().isoformat()
    doc = {
        "user_id": user_id,
        "name": data["name"].strip(),
        "description": (data.get("description") or "").strip()[:240],
        "strategy_type": data["strategy_type"],
        "strategy_id": data["strategy_id"],
        "watchlist": data["watchlist"],
        "schedule": data["schedule"],
        "broker": data["broker"],
        "sizing_mode": data.get("sizing_mode", "fixed_pct"),
        "sizing_pct": float(data.get("sizing_pct", 1.0)),
        "min_confidence": int(data.get("min_confidence", 60)),
        "enabled": enabled,
        "created_at": now,
        "updated_at": now,
        "last_run_at": None,
        "next_run_at": None,
        "stats": {"runs": 0, "signals_fired": 0, "orders_placed": 0, "orders_rejected": 0},
    }
    r = await col_bots.insert_one(doc)
    doc["_id"] = str(r.inserted_id)
    log.info(f"user {user_id} created bot '{doc['name']}' ({doc['_id']}) enabled={enabled}")
    return doc


async def update_bot(user_id: str, bot_id: str, data: dict) -> dict:
    existing = await get_bot(user_id, bot_id)
    if not existing:
        return {"error": "bot not found"}

    merged = {**existing, **data}
    err = _validate_definition(merged)
    if err:
        return {"error": err}

    # If toggling to enabled, require risk limits
    if data.get("enabled") is True and not existing.get("enabled"):
        from services import risk_engine
        if not await risk_engine.is_configured(user_id):
            return {"error": "Risk limits not configured. Set them in Settings before enabling a bot."}

    update = {k: v for k, v in data.items() if k in (
        "name", "description", "strategy_type", "strategy_id",
        "watchlist", "schedule", "broker", "sizing_mode", "sizing_pct",
        "min_confidence", "enabled",
    )}
    update["updated_at"] = datetime.utcnow().isoformat()
    await col_bots.update_one({"_id": ObjectId(bot_id), "user_id": user_id}, {"$set": update})

    log.info(f"user {user_id} updated bot {bot_id}: {list(update.keys())}")
    return await get_bot(user_id, bot_id)


async def delete_bot(user_id: str, bot_id: str) -> dict:
    try:
        oid = ObjectId(bot_id)
    except Exception:
        return {"error": "invalid bot_id"}
    res = await col_bots.delete_one({"_id": oid, "user_id": user_id})
    if res.deleted_count == 0:
        return {"error": "bot not found"}
    # Clean up executions
    await col_executions.delete_many({"user_id": user_id, "bot_id": bot_id})
    log.info(f"user {user_id} deleted bot {bot_id}")
    return {"deleted": 1}


async def toggle_bot(user_id: str, bot_id: str, enabled: bool) -> dict:
    return await update_bot(user_id, bot_id, {"enabled": bool(enabled)})


async def get_executions(user_id: str, bot_id: str, limit: int = 50) -> list:
    """Recent signal evaluations + order outcomes for a bot."""
    docs = await col_executions.find(
        {"user_id": user_id, "bot_id": bot_id}
    ).sort("ran_at", -1).limit(limit).to_list(limit)
    for d in docs:
        d["_id"] = str(d["_id"])
    return docs


async def record_execution(user_id: str, bot_id: str, ticker: str, asset_type: str,
                           signal: str, confidence: float, action: str,
                           order_result: Optional[dict] = None, reason: str = "") -> str:
    """Log one signal evaluation. action = 'placed' | 'skipped' | 'rejected'"""
    doc = {
        "user_id": user_id,
        "bot_id": bot_id,
        "ticker": ticker.upper(),
        "asset_type": asset_type,
        "signal": signal,
        "confidence": float(confidence),
        "action": action,
        "reason": reason,
        "order_result": order_result,
        "ran_at": datetime.utcnow().isoformat(),
    }
    r = await col_executions.insert_one(doc)
    return str(r.inserted_id)


async def get_active_bots() -> list:
    """All enabled bots across all users — used by the runner."""
    docs = await col_bots.find({"enabled": True}).to_list(1000)
    for d in docs:
        d["_id"] = str(d["_id"])
    return docs
