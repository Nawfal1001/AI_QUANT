"""
Drawdown-Triggered Defensive Mode.
Monitors equity drawdown and triggers protective measures.
"""
from datetime import datetime, timedelta
from database import db

def_col = db["defensive_mode"]
hist_col = db["trade_history"]

DEFAULT_THRESHOLDS = {
    "warn_dd_pct": 3.0,        # warn at -3% in 24h
    "defensive_dd_pct": 5.0,   # defensive at -5%
    "halt_dd_pct": 10.0,        # full halt at -10%
}

async def calculate_recent_pnl(hours=24):
    """Calculate P&L over last N hours.

    Returns:
      total_pnl    : naive sum of pnl_pct (kept for backward-compat with callers
                     that report a quick % indicator)
      compounded_pct : compounded portfolio impact (1.005 * 0.99 * ... - 1) * 100,
                     suitable for "are we down 5% in 24h" defensive checks.
    """
    cutoff = (datetime.utcnow() - timedelta(hours=hours)).isoformat()
    trades = await hist_col.find({"closed_at":{"$gte":cutoff}}).to_list(500)
    if not trades:
        return {"total_pnl":0,"compounded_pct":0,"trades":0,"wins":0,"losses":0}
    pnls = [float(t.get("pnl_pct", 0) or 0) for t in trades]
    compounded = 1.0
    for p in pnls:
        compounded *= (1 + p / 100.0)
    compounded_pct = (compounded - 1) * 100
    return {
        "total_pnl": round(sum(pnls), 3),
        "compounded_pct": round(compounded_pct, 3),
        "trades": len(trades),
        "wins": sum(1 for p in pnls if p > 0),
        "losses": sum(1 for p in pnls if p <= 0),
        "avg_pnl": round(sum(pnls) / len(pnls), 3) if pnls else 0,
    }

async def check_defensive_mode():
    """Check if defensive measures should be active.

    Uses compounded 24h portfolio impact (not naive sum of pnl_pct) so winning
    trades correctly net against losing ones.
    """
    pnl_24h = await calculate_recent_pnl(24)
    total_pnl = pnl_24h.get("compounded_pct", pnl_24h.get("total_pnl", 0))
    doc = await def_col.find_one({"_id":"state"})
    thresholds = (doc or {}).get("thresholds", DEFAULT_THRESHOLDS)
    if total_pnl <= -thresholds["halt_dd_pct"]:
        mode = "HALT"; reason = f"24h drawdown {total_pnl:.2f}% ≥ halt threshold"
        adjustments = {"halt_trading":True,"size_multiplier":0,"min_confidence":100}
    elif total_pnl <= -thresholds["defensive_dd_pct"]:
        mode = "DEFENSIVE"; reason = f"24h drawdown {total_pnl:.2f}% — defensive mode"
        adjustments = {"halt_trading":False,"size_multiplier":0.5,"min_confidence":80,"allowed_regimes":["RANGING","QUIET"]}
    elif total_pnl <= -thresholds["warn_dd_pct"]:
        mode = "WARNING"; reason = f"24h drawdown {total_pnl:.2f}% — caution"
        adjustments = {"halt_trading":False,"size_multiplier":0.75,"min_confidence":75}
    else:
        mode = "NORMAL"; reason = f"24h P&L {total_pnl:+.2f}% — normal operations"
        adjustments = {"halt_trading":False,"size_multiplier":1.0,"min_confidence":70}
    state = {"_id":"state","mode":mode,"reason":reason,"adjustments":adjustments,
             "pnl_24h":pnl_24h,"thresholds":thresholds,"checked_at":datetime.utcnow().isoformat()}
    await def_col.replace_one({"_id":"state"},state,upsert=True)
    state.pop("_id",None)
    return state

async def get_state():
    doc = await def_col.find_one({"_id":"state"})
    if not doc:
        return await check_defensive_mode()
    doc.pop("_id",None); return doc

async def update_thresholds(thresholds):
    await def_col.update_one({"_id":"state"},{"$set":{"thresholds":thresholds}},upsert=True)
    return {"status":"updated","thresholds":thresholds}
