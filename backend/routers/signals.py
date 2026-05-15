"""Signals router — requires auth. Logs signals against user_id for performance tracking."""
import asyncio
from fastapi import APIRouter, Depends

from services.signal_service import generate_signal
from services import signal_tracker
from middleware.auth import get_current_user

router = APIRouter()


@router.get("/{ticker}")
async def signal(ticker: str, asset_type: str = "stock", timeframe: str = "swing", use_ai: bool = False, user=Depends(get_current_user)):
    result = await generate_signal(ticker.upper(), asset_type, timeframe, use_ai=use_ai)
    # Log for performance tracking if it's an actionable signal
    if result and result.get("signal") not in (None, "HOLD") and result.get("confidence", 0) >= 50:
        try:
            sig_id = await signal_tracker.log_signal(
                user_id=user["id"],
                ticker=ticker.upper(),
                signal=result["signal"],
                confidence=result["confidence"],
                strategy=result.get("strategy", "default"),
                timeframe=timeframe,
                regime=result.get("regime", "unknown"),
                asset_type=asset_type,
                metadata={"price": result.get("price")},
            )
            result["signal_id"] = sig_id
        except Exception:
            pass
    return result


@router.get("/multi/{ticker}")
async def multi(ticker: str, asset_type: str = "stock", user=Depends(get_current_user)):
    tfs = ["scalping", "intraday", "swing", "position"]
    results = await asyncio.gather(
        *[generate_signal(ticker.upper(), asset_type, tf) for tf in tfs],
        return_exceptions=True,
    )
    return {tf: r for tf, r in zip(tfs, results) if not isinstance(r, Exception)}


@router.get("/opportunities/best")
async def opportunities(asset_type: str = "all", limit: int = 10, timeframe: str = "swing", user=Depends(get_current_user)):
    stocks = ["AAPL", "NVDA", "TSLA", "MSFT", "AMZN", "META", "GOOGL", "AMD"]
    cryptos = ["BTC", "ETH", "SOL", "BNB", "ADA", "XRP"]
    if asset_type == "stock":
        items = [(t, "stock") for t in stocks]
    elif asset_type == "crypto":
        items = [(t, "crypto") for t in cryptos]
    else:
        items = [(t, "stock") for t in stocks] + [(t, "crypto") for t in cryptos]
    results = await asyncio.gather(
        *[generate_signal(t, at, timeframe) for t, at in items[:12]],
        return_exceptions=True,
    )
    sigs = [
        r for r in results
        if not isinstance(r, Exception) and r.get("signal") not in ("HOLD", None) and r.get("confidence", 0) >= 60
    ]
    sigs.sort(key=lambda x: x.get("confidence", 0), reverse=True)
    return {"opportunities": sigs[:limit]}
