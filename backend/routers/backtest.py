"""Backtest router — user-scoped, multi-strategy."""
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException

from middleware.auth import get_current_user, scope_filter
from services.backtest_engine import run_backtest, run_compare
from services.strategies import list_strategies
from services.logger import child
from database import db

log = child("backtest_router")
router = APIRouter()
col = db["backtests"]


@router.get("/strategies")
async def strategies():
    # Public: just lists available strategy metadata (names + descriptions)
    return {"strategies": list_strategies()}


VALID_INTERVALS = {"1d", "4h", "1h", "15m"}
MAX_BACKTEST_DAYS = 3650  # ~10 years


@router.post("/run")
async def run(req: dict, user=Depends(get_current_user)):
    ticker = (req.get("ticker") or "AAPL").upper()
    asset_type = req.get("asset_type", "stock")
    try:
        capital = float(req.get("capital", 10000))
        days = int(req.get("days", 365))
    except (TypeError, ValueError):
        raise HTTPException(400, "capital and days must be numeric")
    if capital <= 0 or capital > 1e10:
        raise HTTPException(400, "capital out of range")
    if days <= 0 or days > MAX_BACKTEST_DAYS:
        raise HTTPException(400, f"days must be 1..{MAX_BACKTEST_DAYS}")
    interval = req.get("interval", "1d")
    if interval not in VALID_INTERVALS:
        raise HTTPException(400, f"interval must be one of {sorted(VALID_INTERVALS)}")
    strategy = req.get("strategy", "ensemble")
    user_strategy_id = req.get("user_strategy_id")

    custom_def = None
    # If the user passes a user_strategy_id, load and use that definition.
    if user_strategy_id:
        from services.user_strategies import get_user_strategy
        doc = await get_user_strategy(user["id"], user_strategy_id)
        if not doc:
            return {"error": f"User strategy {user_strategy_id} not found"}
        custom_def = doc

    end = datetime.now().strftime("%Y-%m-%d")
    start = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")

    result = await run_backtest(
        ticker=ticker,
        asset_type=asset_type,
        start_date=start,
        end_date=end,
        interval=interval,
        initial_capital=capital,
        risk_per_trade=float(req.get("risk_per_trade", 0.02)),
        min_confidence=int(req.get("min_confidence", 55)),
        sl_atr_mult=float(req.get("sl_atr_mult", 2.0)),
        tp_atr_mult=float(req.get("tp_atr_mult", 3.0)),
        fee_bps=float(req.get("fee_bps", 5)),
        slippage_bps=float(req.get("slippage_bps", 3)),
        spread_bps=float(req.get("spread_bps", 2)),
        max_hold_bars=int(req.get("max_hold_bars", 30)),
        strategy=strategy,
        custom_strategy_def=custom_def,
    )

    if "error" not in result:
        try:
            save_doc = {
                **{k: v for k, v in result.items() if k not in ("equity_curve", "trades", "drawdown_curve")},
                "user_id": user["id"],
                "trades_count": result.get("total_trades", 0),
                "saved_at": datetime.utcnow().isoformat(),
            }
            await col.insert_one(save_doc)
        except Exception as e:
            log.exception(f"failed to save backtest: {e}")

    return result


@router.post("/compare")
async def compare(req: dict, user=Depends(get_current_user)):
    """Compare multiple strategies on the same period."""
    ticker = (req.get("ticker") or "AAPL").upper()
    asset_type = req.get("asset_type", "stock")
    try:
        capital = float(req.get("capital", 10000))
        days = int(req.get("days", 365))
    except (TypeError, ValueError):
        raise HTTPException(400, "capital and days must be numeric")
    if capital <= 0 or capital > 1e10 or days <= 0 or days > MAX_BACKTEST_DAYS:
        raise HTTPException(400, "capital/days out of range")
    interval = req.get("interval", "1d")
    if interval not in VALID_INTERVALS:
        raise HTTPException(400, f"interval must be one of {sorted(VALID_INTERVALS)}")
    raw_strategies = req.get("strategies") or ["trend_follow", "mean_revert", "breakout", "ensemble"]
    if not isinstance(raw_strategies, list) or len(raw_strategies) > 20:
        raise HTTPException(400, "strategies must be a list of <= 20 names")
    strategies_to_run = raw_strategies

    end = datetime.now().strftime("%Y-%m-%d")
    start = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")

    return await run_compare(
        ticker=ticker,
        asset_type=asset_type,
        start_date=start,
        end_date=end,
        interval=interval,
        initial_capital=capital,
        strategies=strategies_to_run,
        risk_per_trade=float(req.get("risk_per_trade", 0.02)),
        min_confidence=int(req.get("min_confidence", 55)),
    )


@router.get("/history")
async def history(limit: int = 20, user=Depends(get_current_user)):
    q = scope_filter(user)
    docs = await col.find(q).sort("saved_at", -1).limit(limit).to_list(limit)
    for d in docs:
        d["_id"] = str(d["_id"])
    return {"backtests": docs, "count": len(docs)}


@router.delete("/history")
async def clear_history(user=Depends(get_current_user)):
    q = scope_filter(user)
    res = await col.delete_many(q)
    return {"deleted": res.deleted_count}


@router.get("/timeframes")
async def tfs():
    return {
        "intervals": ["1d", "4h", "1h", "15m"],
        "presets": [
            {"label": "Last 90 days", "days": 90},
            {"label": "Last 6 months", "days": 180},
            {"label": "Last 1 year", "days": 365},
            {"label": "Last 2 years", "days": 730},
        ],
    }
