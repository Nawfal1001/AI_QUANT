"""
Dynamic Symbol Scanner.

Ranks a universe of symbols for daily watchlist updates using:
- market momentum
- volume expansion
- volatility / tradability
- simple RSS sentiment
- optional Gemini AI sentiment

This service does not place trades. It produces ranked candidates that bots can
use to refresh their watchlists once per day.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from functools import partial
from typing import Any, Dict, List, Optional

import feedparser
import pandas as pd

from database import db
from services.logger import child
from services.backtest_engine import fetch_history

log = child("symbol_scanner")

col_scan_runs = db["symbol_scan_runs"]
col_scan_cache = db["symbol_scan_cache"]

DEFAULT_CRYPTO_UNIVERSE = [
    "BTC", "ETH", "SOL", "BNB", "XRP", "ADA", "DOGE", "AVAX", "LINK", "DOT",
    "TRX", "MATIC", "LTC", "BCH", "ATOM", "NEAR", "APT", "ARB", "OP", "INJ",
]

DEFAULT_STOCK_UNIVERSE = [
    "AAPL", "MSFT", "NVDA", "TSLA", "META", "AMZN", "GOOGL", "AMD", "NFLX", "COIN",
]

POSITIVE_WORDS = ["surge", "gain", "bull", "beat", "rise", "growth", "profit", "strong", "up", "record", "upgrade", "rally", "breakout"]
NEGATIVE_WORDS = ["drop", "fall", "bear", "miss", "loss", "weak", "crash", "concern", "down", "downgrade", "lawsuit", "probe", "selloff"]


def _clamp(x: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, x))


def _safe_float(x: Any, default: float = 0.0) -> float:
    try:
        if pd.isna(x):
            return default
        return float(x)
    except Exception:
        return default


def _score_sentiment_from_headlines(headlines: List[str]) -> Dict[str, Any]:
    raw = 0
    hits = []
    for h in headlines:
        hl = h.lower()
        for w in POSITIVE_WORDS:
            if w in hl:
                raw += 1
                hits.append(f"+{w}")
        for w in NEGATIVE_WORDS:
            if w in hl:
                raw -= 1
                hits.append(f"-{w}")
    sentiment = "bullish" if raw > 2 else "bearish" if raw < -2 else "neutral"
    normalized = _clamp(50 + raw * 8)
    return {"raw": raw, "score": round(normalized, 2), "sentiment": sentiment, "hits": hits[:10]}


async def fetch_news_sentiment(ticker: str) -> Dict[str, Any]:
    """Fetch/cache simple Yahoo RSS headline sentiment."""
    cached = await col_scan_cache.find_one({"kind": "news", "ticker": ticker.upper()})
    if cached:
        ts = datetime.fromisoformat(cached.get("updated_at"))
        if datetime.utcnow() - ts < timedelta(hours=6):
            return cached["data"]

    def _fetch():
        feed = feedparser.parse(f"https://feeds.finance.yahoo.com/rss/2.0/headline?s={ticker}&region=US&lang=en-US")
        return [e.get("title", "") for e in feed.entries[:12]]

    try:
        loop = asyncio.get_event_loop()
        headlines = await loop.run_in_executor(None, _fetch)
        scored = _score_sentiment_from_headlines(headlines)
        data = {"ticker": ticker.upper(), "headlines": headlines[:5], **scored}
    except Exception as e:
        data = {"ticker": ticker.upper(), "headlines": [], "raw": 0, "score": 50, "sentiment": "neutral", "error": str(e)}

    await col_scan_cache.replace_one(
        {"kind": "news", "ticker": ticker.upper()},
        {"kind": "news", "ticker": ticker.upper(), "data": data, "updated_at": datetime.utcnow().isoformat()},
        upsert=True,
    )
    return data


async def fetch_ai_sentiment(ticker: str, asset_type: str, enabled: bool = False) -> Dict[str, Any]:
    """Optional AI sentiment. Disabled by default to avoid slow/expensive daily scans."""
    if not enabled:
        return {"score": 50, "confidence": 0, "reason": "AI disabled for scan"}

    cached = await col_scan_cache.find_one({"kind": "ai", "ticker": ticker.upper(), "asset_type": asset_type})
    if cached:
        ts = datetime.fromisoformat(cached.get("updated_at"))
        if datetime.utcnow() - ts < timedelta(hours=12):
            return cached["data"]

    try:
        from services.ai_service import get_ai_signal
        ai = await get_ai_signal(ticker, asset_type)
        raw = _safe_float(ai.get("score", 0))
        confidence = _safe_float(ai.get("confidence", 50))
        data = {
            "score": _clamp(50 + raw * 35),
            "raw": raw,
            "confidence": confidence,
            "reason": ai.get("reason", "AI sentiment"),
        }
    except Exception as e:
        data = {"score": 50, "confidence": 0, "reason": f"AI unavailable: {e}"}

    await col_scan_cache.replace_one(
        {"kind": "ai", "ticker": ticker.upper(), "asset_type": asset_type},
        {"kind": "ai", "ticker": ticker.upper(), "asset_type": asset_type, "data": data, "updated_at": datetime.utcnow().isoformat()},
        upsert=True,
    )
    return data


async def fetch_market_features(ticker: str, asset_type: str, interval: str = "1d") -> Dict[str, Any]:
    end = datetime.utcnow()
    start = end - timedelta(days=90)
    try:
        df = await fetch_history(ticker, asset_type, start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d"), interval)
        if df is None or len(df) < 35:
            return {"ticker": ticker.upper(), "error": "insufficient history", "score": 0}
        close = df["close"].astype(float)
        volume = df["volume"].astype(float)
        high = df["high"].astype(float)
        low = df["low"].astype(float)

        last = _safe_float(close.iloc[-1])
        ret_1d = (last / _safe_float(close.iloc[-2], last) - 1) * 100 if len(close) >= 2 else 0
        ret_7d = (last / _safe_float(close.iloc[-8], last) - 1) * 100 if len(close) >= 8 else 0
        ret_30d = (last / _safe_float(close.iloc[-31], last) - 1) * 100 if len(close) >= 31 else 0
        vol_ratio = _safe_float(volume.iloc[-1]) / max(_safe_float(volume.rolling(20).mean().iloc[-1], 1), 1)
        atr_pct = _safe_float(((high - low).rolling(14).mean().iloc[-1] / last) * 100)

        momentum_score = _clamp(50 + ret_7d * 4 + ret_30d * 1.2)
        volume_score = _clamp(45 + (vol_ratio - 1) * 35)
        volatility_score = _clamp(100 - abs(atr_pct - 3.0) * 12)  # prefer tradable, not dead or insane
        trend_score = _clamp(50 + ret_1d * 4 + ret_7d * 2)

        return {
            "ticker": ticker.upper(),
            "last_price": round(last, 6),
            "ret_1d_pct": round(ret_1d, 3),
            "ret_7d_pct": round(ret_7d, 3),
            "ret_30d_pct": round(ret_30d, 3),
            "volume_ratio": round(vol_ratio, 3),
            "atr_pct": round(atr_pct, 3),
            "momentum_score": round(momentum_score, 2),
            "volume_score": round(volume_score, 2),
            "volatility_score": round(volatility_score, 2),
            "trend_score": round(trend_score, 2),
        }
    except Exception as e:
        log.warning(f"market feature scan failed for {ticker}: {e}")
        return {"ticker": ticker.upper(), "error": str(e), "score": 0}


def _combine_scores(market: Dict[str, Any], news: Dict[str, Any], ai: Dict[str, Any]) -> Dict[str, Any]:
    if market.get("error"):
        return {"score": 0, "reason": market.get("error", "market error")}
    market_score = (
        market.get("momentum_score", 50) * 0.35
        + market.get("volume_score", 50) * 0.25
        + market.get("volatility_score", 50) * 0.20
        + market.get("trend_score", 50) * 0.20
    )
    news_score = _safe_float(news.get("score", 50), 50)
    ai_score = _safe_float(ai.get("score", 50), 50)
    ai_weight = 0.10 if _safe_float(ai.get("confidence", 0)) >= 40 else 0.0
    news_weight = 0.15
    technical_weight = 1.0 - news_weight - ai_weight
    total = market_score * technical_weight + news_score * news_weight + ai_score * ai_weight

    reasons = [
        f"momentum {market.get('ret_7d_pct', 0)}%/7d",
        f"volume x{market.get('volume_ratio', 0)}",
        f"ATR {market.get('atr_pct', 0)}%",
        f"news {news.get('sentiment', 'neutral')} ({news.get('raw', 0)})",
    ]
    if ai_weight:
        reasons.append(f"AI {ai.get('raw', 0)} conf {ai.get('confidence', 0)}")
    return {"score": round(_clamp(total), 2), "reason": "; ".join(reasons)}


async def score_symbol(ticker: str, asset_type: str = "crypto", interval: str = "1d", use_ai: bool = False) -> Dict[str, Any]:
    market, news, ai = await asyncio.gather(
        fetch_market_features(ticker, asset_type, interval),
        fetch_news_sentiment(ticker),
        fetch_ai_sentiment(ticker, asset_type, enabled=use_ai),
    )
    combined = _combine_scores(market, news, ai)
    return {
        "ticker": ticker.upper(),
        "asset_type": asset_type,
        "score": combined["score"],
        "reason": combined["reason"],
        "market": market,
        "news": news,
        "ai": ai,
    }


async def scan_universe(
    universe: Optional[List[str]] = None,
    asset_type: str = "crypto",
    interval: str = "1d",
    limit: int = 10,
    use_ai: bool = False,
) -> Dict[str, Any]:
    if universe is None:
        universe = DEFAULT_CRYPTO_UNIVERSE if asset_type == "crypto" else DEFAULT_STOCK_UNIVERSE
    universe = [s.upper().strip() for s in universe if s and isinstance(s, str)]
    tasks = [score_symbol(s, asset_type=asset_type, interval=interval, use_ai=use_ai) for s in universe]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    ranked = []
    for r in results:
        if isinstance(r, dict):
            ranked.append(r)
        else:
            log.warning(f"symbol scan item failed: {r}")
    ranked.sort(key=lambda x: x.get("score", 0), reverse=True)
    selected = ranked[:limit]
    run = {
        "asset_type": asset_type,
        "interval": interval,
        "limit": limit,
        "use_ai": use_ai,
        "universe_size": len(universe),
        "selected": selected,
        "ranked": ranked,
        "created_at": datetime.utcnow().isoformat(),
    }
    try:
        await col_scan_runs.insert_one(run)
    except Exception as e:
        log.debug(f"failed to store scan run: {e}")
    return {k: v for k, v in run.items() if k != "_id"}


async def update_dynamic_bot_watchlists(
    asset_type: str = "crypto",
    interval: str = "1d",
    limit: int = 10,
    use_ai: bool = False,
) -> Dict[str, Any]:
    """Refresh watchlists for bots that opt in with use_dynamic_watchlist=True."""
    scan = await scan_universe(asset_type=asset_type, interval=interval, limit=limit, use_ai=use_ai)
    watchlist = [{"ticker": x["ticker"], "asset_type": x.get("asset_type", asset_type)} for x in scan["selected"]]
    res = await db["bots"].update_many(
        {"use_dynamic_watchlist": True, "dynamic_asset_type": asset_type},
        {"$set": {
            "watchlist": watchlist,
            "last_watchlist_scan_at": datetime.utcnow().isoformat(),
            "last_watchlist_scan_score": [{"ticker": x["ticker"], "score": x["score"], "reason": x["reason"]} for x in scan["selected"]],
        }},
    )
    return {"updated_bots": res.modified_count, "watchlist": watchlist, "scan": scan}
