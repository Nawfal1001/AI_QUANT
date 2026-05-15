"""Signal performance router — user-scoped."""
from fastapi import APIRouter, Depends, HTTPException, Query
from middleware.auth import get_current_user
from services import signal_tracker

router = APIRouter()


@router.get("/recent")
async def recent(limit: int = Query(50, ge=1, le=500), user=Depends(get_current_user)):
    return {"signals": await signal_tracker.recent_signals(user["id"], limit)}


@router.get("/stats/{group_by}")
async def stats(group_by: str, user=Depends(get_current_user)):
    if group_by not in ["strategy", "ticker", "timeframe", "regime"]:
        raise HTTPException(400, "group_by must be strategy/ticker/timeframe/regime")
    return {"stats": await signal_tracker.get_stats(user["id"], group_by)}


@router.get("/weights")
async def weights(user=Depends(get_current_user)):
    """Return current strategy weights derived from rolling performance."""
    return {"weights": await signal_tracker.get_strategy_weights(user["id"])}


@router.post("/log")
async def log_one(payload: dict, user=Depends(get_current_user)):
    """Manually log a signal (mainly for testing — auto-tracker logs from signal_service)."""
    sig_id = await signal_tracker.log_signal(
        user_id=user["id"],
        ticker=payload.get("ticker", ""),
        signal=payload.get("signal", "HOLD"),
        confidence=payload.get("confidence", 0),
        strategy=payload.get("strategy", "default"),
        timeframe=payload.get("timeframe", "swing"),
        regime=payload.get("regime", "unknown"),
        asset_type=payload.get("asset_type", "stock"),
        metadata=payload.get("metadata"),
    )
    return {"signal_id": sig_id}


@router.post("/resolve/{signal_id}")
async def resolve(signal_id: str, payload: dict, user=Depends(get_current_user)):
    try:
        pnl_pct = float(payload.get("pnl_pct", 0))
    except (TypeError, ValueError):
        raise HTTPException(400, "pnl_pct must be numeric")
    res = await signal_tracker.resolve_signal(
        signal_id=signal_id,
        outcome=payload.get("outcome", "expired"),
        pnl_pct=pnl_pct,
        user_id=user["id"],
    )
    if "error" in res:
        raise HTTPException(400, res["error"])
    return res
