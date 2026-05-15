"""
Risk Engine.
Enforces hard limits before any order is placed. All limits are per-user.
Limits stored in db['risk_limits'] indexed by user_id.

Required limits (no defaults — user must set them in Settings):
- daily_loss_limit_pct   : float (e.g. 2.0 = stop trading after 2% account loss today)
- max_drawdown_pct       : float (e.g. 10.0 = halt if equity < peak * 0.90)
- max_open_trades        : int
- max_position_size_pct  : float (e.g. 5.0 = no single position > 5% of equity)
- kill_switch            : bool (true = block ALL new orders immediately)
"""
from datetime import datetime, timedelta
from typing import Optional

from database import db
from services.logger import child

log = child("risk")

REQUIRED_FIELDS = [
    "daily_loss_limit_pct",
    "max_drawdown_pct",
    "max_open_trades",
    "max_position_size_pct",
]

col_limits = db["risk_limits"]
col_state = db["risk_state"]    # caches daily-loss tracker, peak equity per user
col_trades = db["trades"]
col_paper_accounts = db["paper_accounts"]
col_paper_positions = db["paper_positions"]


async def get_limits(user_id: str) -> Optional[dict]:
    """Returns the user's limits dict or None if not configured."""
    return await col_limits.find_one({"user_id": user_id})


async def is_configured(user_id: str) -> bool:
    """User has set all required risk limits."""
    lim = await get_limits(user_id)
    if not lim:
        return False
    return all(lim.get(f) is not None for f in REQUIRED_FIELDS)


async def set_limits(user_id: str, limits: dict) -> dict:
    """Save risk limits. Validates all required fields are present and numeric."""
    cleaned = {}
    for f in REQUIRED_FIELDS:
        v = limits.get(f)
        if v is None or v == "":
            return {"error": f"Missing required field: {f}"}
        try:
            cleaned[f] = float(v) if "pct" in f else int(v)
        except (ValueError, TypeError):
            return {"error": f"Invalid value for {f}"}
        if cleaned[f] <= 0:
            return {"error": f"{f} must be positive"}
    cleaned["kill_switch"] = bool(limits.get("kill_switch", False))
    cleaned["user_id"] = user_id
    cleaned["updated_at"] = datetime.utcnow().isoformat()
    await col_limits.replace_one({"user_id": user_id}, cleaned, upsert=True)
    log.info(f"user {user_id} updated risk limits: {cleaned}")
    return {"status": "saved", "limits": cleaned}


async def set_kill_switch(user_id: str, enabled: bool) -> dict:
    """Toggle the kill switch. Blocks all new orders when enabled."""
    res = await col_limits.update_one(
        {"user_id": user_id},
        {"$set": {"kill_switch": bool(enabled), "kill_switch_at": datetime.utcnow().isoformat()}},
        upsert=True,
    )
    log.warning(f"user {user_id} kill_switch = {enabled}")
    return {"kill_switch": bool(enabled)}


async def get_daily_pnl(user_id: str) -> float:
    """Sum of PnL on trades closed today (UTC), per user."""
    start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
    cursor = col_trades.find({
        "user_id": user_id,
        "closed_at": {"$gte": start},
        "status": "closed",
    })
    total = 0.0
    async for t in cursor:
        try:
            total += float(t.get("pnl", 0))
        except (TypeError, ValueError):
            continue
    return total


async def get_open_trade_count(user_id: str) -> int:
    return await col_trades.count_documents({"user_id": user_id, "status": "open"})


async def get_account_equity(user_id: str) -> float:
    """Mark-to-market equity.

    Prefers the paper_accounts cash balance plus mark-to-market value of open paper
    positions when a paper account exists for the user. Falls back to
    starting_capital (configured per-user in risk_state) + cumulative realized PnL
    so live-only users still get a reasonable equity figure.
    """
    acct = await col_paper_accounts.find_one({"user_id": user_id})
    if acct:
        cash = float(acct.get("cash", acct.get("starting_capital", 0)) or 0)
        # Mark-to-market open paper positions against the freshness cache.
        from services import data_freshness
        positions = await col_paper_positions.find({"user_id": user_id}).to_list(500)
        mv = 0.0
        for p in positions:
            qty = float(p.get("qty", 0) or 0)
            cached = data_freshness.get_price(p.get("ticker", ""))
            price = (cached["price"] if cached else None) or float(p.get("avg_entry", 0) or 0)
            mv += qty * price
        return cash + mv

    state = await col_state.find_one({"user_id": user_id}) or {}
    starting = float(state.get("starting_capital", 10000))
    pipeline = [
        {"$match": {"user_id": user_id, "status": "closed"}},
        {"$group": {"_id": None, "pnl": {"$sum": "$pnl"}}},
    ]
    realized = 0.0
    async for r in col_trades.aggregate(pipeline):
        realized = float(r.get("pnl", 0) or 0)
    return starting + realized


async def get_peak_equity(user_id: str) -> float:
    state = await col_state.find_one({"user_id": user_id}) or {}
    current = await get_account_equity(user_id)
    peak = float(state.get("peak_equity", current))
    if current > peak:
        peak = current
        await col_state.update_one(
            {"user_id": user_id},
            {"$set": {"peak_equity": peak, "peak_at": datetime.utcnow().isoformat()}},
            upsert=True,
        )
    return peak


async def check_order(user_id: str, position_size_usd: float, ticker: str = "") -> dict:
    """
    Returns {"allowed": True} or {"allowed": False, "reason": "..."}.
    Run this immediately before placing an order (paper OR live).
    """
    limits = await get_limits(user_id)
    if not limits or not all(limits.get(f) is not None for f in REQUIRED_FIELDS):
        return {"allowed": False, "reason": "Risk limits not configured. Set them in Settings before trading."}

    if limits.get("kill_switch"):
        return {"allowed": False, "reason": "Kill switch active — all new orders blocked"}

    equity = await get_account_equity(user_id)

    # Daily loss
    daily_pnl = await get_daily_pnl(user_id)
    daily_loss_pct = -daily_pnl / equity * 100 if equity > 0 else 0
    if daily_pnl < 0 and daily_loss_pct >= limits["daily_loss_limit_pct"]:
        return {
            "allowed": False,
            "reason": f"Daily loss limit hit ({daily_loss_pct:.2f}% >= {limits['daily_loss_limit_pct']}%)",
        }

    # Max drawdown
    peak = await get_peak_equity(user_id)
    dd_pct = (peak - equity) / peak * 100 if peak > 0 else 0
    if dd_pct >= limits["max_drawdown_pct"]:
        return {
            "allowed": False,
            "reason": f"Max drawdown hit ({dd_pct:.2f}% >= {limits['max_drawdown_pct']}%)",
        }

    # Open trade count
    open_count = await get_open_trade_count(user_id)
    if open_count >= limits["max_open_trades"]:
        return {
            "allowed": False,
            "reason": f"Max open trades reached ({open_count}/{limits['max_open_trades']})",
        }

    # Position size
    pos_pct = position_size_usd / equity * 100 if equity > 0 else 100
    if pos_pct > limits["max_position_size_pct"]:
        return {
            "allowed": False,
            "reason": f"Position too large ({pos_pct:.2f}% > {limits['max_position_size_pct']}% of equity)",
        }

    return {"allowed": True, "equity": equity, "daily_pnl": daily_pnl, "drawdown_pct": dd_pct, "open_trades": open_count}


async def get_status(user_id: str) -> dict:
    """Returns current risk usage dashboard for UI."""
    limits = await get_limits(user_id) or {}
    equity = await get_account_equity(user_id)
    peak = await get_peak_equity(user_id)
    daily_pnl = await get_daily_pnl(user_id)
    open_count = await get_open_trade_count(user_id)
    dd_pct = (peak - equity) / peak * 100 if peak > 0 else 0
    daily_loss_pct = -daily_pnl / equity * 100 if (equity > 0 and daily_pnl < 0) else 0

    return {
        "configured": all(limits.get(f) is not None for f in REQUIRED_FIELDS),
        "kill_switch": bool(limits.get("kill_switch", False)),
        "equity": round(equity, 2),
        "peak_equity": round(peak, 2),
        "daily_pnl": round(daily_pnl, 2),
        "daily_loss_pct": round(daily_loss_pct, 2),
        "drawdown_pct": round(dd_pct, 2),
        "open_trades": open_count,
        "limits": {f: limits.get(f) for f in REQUIRED_FIELDS},
        "limits_usage": {
            "daily_loss": {"used": round(daily_loss_pct, 2), "limit": limits.get("daily_loss_limit_pct")},
            "drawdown": {"used": round(dd_pct, 2), "limit": limits.get("max_drawdown_pct")},
            "open_trades": {"used": open_count, "limit": limits.get("max_open_trades")},
        },
    }
