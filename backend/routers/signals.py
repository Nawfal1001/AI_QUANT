"""Signals router — requires auth. Logs signals against user_id for performance tracking."""
import asyncio
from datetime import datetime
from fastapi import APIRouter, Depends

from services.signal_service import generate_signal, batch_prefetch_stocks_async
from services import signal_tracker
from middleware.auth import get_current_user

router = APIRouter()

# ── Universe definitions (deduped, verified tickers) ─────────────────────────
STOCK_UNIVERSE = [
    # Mega-cap tech
    "AAPL","NVDA","MSFT","AMZN","META","GOOGL","TSLA","AMD","INTC","ORCL",
    # Finance
    "JPM","GS","MS","V","MA","BAC","WFC",
    # Consumer / Retail
    "NFLX","DIS","WMT","COST","TGT","NKE","SBUX",
    # Healthcare / Biotech
    "JNJ","PFE","MRNA","ABBV","UNH","CVS",
    # Energy / Industrial
    "XOM","CVX","BA","CAT","GE","HON",
    # Fintech / Growth
    "PYPL","SQ","COIN","SHOP","UBER","SNAP","RBLX","PLTR","HOOD",
    # ETFs
    "SPY","QQQ","IWM","ARKK","XLF","XLE",
    # High-volatility
    "GME","AMC","SOFI","RIVN","LCID",
]

CRYPTO_UNIVERSE = [
    "BTC","ETH","SOL","BNB","ADA","XRP","DOGE","AVAX","MATIC","DOT",
    "LINK","UNI","LTC","ATOM","NEAR",
]

FOREX_UNIVERSE = [
    "EURUSD=X","GBPUSD=X","USDJPY=X","AUDUSD=X","USDCAD=X","USDCHF=X",
]

# Limit concurrent signal generations to avoid thread-pool saturation
_SCAN_SEM = asyncio.Semaphore(12)


async def _gen_one(ticker, atype, timeframe, use_advanced):
    """Generate signal for one ticker, respecting the concurrency semaphore."""
    async with _SCAN_SEM:
        return await generate_signal(ticker, atype, timeframe, use_advanced=use_advanced)


async def _scan_items(items, timeframe, min_confidence, user_id, use_advanced=False):
    """
    Scan a list of (ticker, asset_type) pairs.
    - Batch-prefetches all stock OHLCV before generating signals (10-30× faster).
    - Limits concurrency to _SCAN_SEM slots.
    - use_advanced=False skips LLM/microstructure/confluence overhead for speed.
    """
    # Batch prefetch all stock tickers at once (single yf.download call)
    stock_tickers = [t for t, at in items if at == "stock"]
    if stock_tickers:
        await batch_prefetch_stocks_async(stock_tickers)

    results = await asyncio.gather(
        *[_gen_one(t, at, timeframe, use_advanced) for t, at in items],
        return_exceptions=True,
    )

    out = []
    for (ticker, atype), r in zip(items, results):
        if isinstance(r, Exception) or not r:
            continue
        if r.get("signal") in ("HOLD", None):
            continue
        if r.get("confidence", 0) < min_confidence:
            continue
        r["asset_type"] = atype
        try:
            await signal_tracker.log_signal(
                user_id=user_id,
                ticker=ticker,
                signal=r["signal"],
                confidence=r["confidence"],
                strategy=r.get("strategy", "default"),
                timeframe=timeframe,
                regime=r.get("regime", "unknown"),
                asset_type=atype,
                metadata={"price": r.get("price")},
            )
        except Exception:
            pass
        out.append(r)
    out.sort(key=lambda x: x.get("confidence", 0), reverse=True)
    return out


# ── Routes ────────────────────────────────────────────────────────────────────

@router.get("/scan/universe")
async def scan_universe(
    asset_type: str = "all",
    timeframe: str = "swing",
    min_confidence: int = 60,
    user=Depends(get_current_user),
):
    """Scan the full symbol universe and return ranked actionable signals."""
    items = []
    if asset_type in ("stock", "all"):
        items += [(t, "stock") for t in STOCK_UNIVERSE]
    if asset_type in ("crypto", "all"):
        items += [(t, "crypto") for t in CRYPTO_UNIVERSE]
    if asset_type == "forex":
        items += [(t, "stock") for t in FOREX_UNIVERSE]

    signals = await _scan_items(items, timeframe, min_confidence, user["id"], use_advanced=False)
    return {
        "scanned": len(items),
        "found": len(signals),
        "timeframe": timeframe,
        "min_confidence": min_confidence,
        "scanned_at": datetime.utcnow().isoformat(),
        "signals": signals,
    }


@router.get("/scan/watchlist")
async def scan_watchlist(
    tickers: str = "",
    asset_type: str = "stock",
    timeframe: str = "swing",
    min_confidence: int = 55,
    user=Depends(get_current_user),
):
    """Scan a custom comma-separated watchlist."""
    ticker_list = [t.strip().upper() for t in tickers.split(",") if t.strip()]
    if not ticker_list:
        return {"signals": [], "scanned": 0, "found": 0}
    items = [(t, asset_type) for t in ticker_list[:50]]
    signals = await _scan_items(items, timeframe, min_confidence, user["id"], use_advanced=False)
    return {
        "scanned": len(items),
        "found": len(signals),
        "timeframe": timeframe,
        "scanned_at": datetime.utcnow().isoformat(),
        "signals": signals,
    }


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


@router.get("/multi/{ticker}")
async def multi(ticker: str, asset_type: str = "stock", user=Depends(get_current_user)):
    tfs = ["scalping", "intraday", "swing", "position"]
    results = await asyncio.gather(
        *[generate_signal(ticker.upper(), asset_type, tf) for tf in tfs],
        return_exceptions=True,
    )
    return {tf: r for tf, r in zip(tfs, results) if not isinstance(r, Exception)}


@router.get("/{ticker}")
async def signal(ticker: str, asset_type: str = "stock", timeframe: str = "swing", use_ai: bool = False, user=Depends(get_current_user)):
    result = await generate_signal(ticker.upper(), asset_type, timeframe, use_ai=use_ai)
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
