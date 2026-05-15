"""
Dynamic Symbol Scanner.

Ranks a broker-compatible universe of symbols for watchlist updates using:
- market momentum
- volume expansion
- volatility / tradability
- simple RSS sentiment
- optional Gemini AI sentiment

Supports broker-aware universes so bots do not receive symbols their broker
cannot trade. Crypto discovery uses CCXT-supported exchanges when available.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

import feedparser
import pandas as pd

from database import db
from services.logger import child
from services.backtest_engine import fetch_history

log = child("symbol_scanner")

col_scan_runs = db["symbol_scan_runs"]
col_scan_cache = db["symbol_scan_cache"]

DEFAULT_CRYPTO_UNIVERSE = ["BTC", "ETH", "SOL", "BNB", "XRP", "ADA", "DOGE", "AVAX", "LINK", "DOT", "TRX", "MATIC", "LTC", "BCH", "ATOM", "NEAR", "APT", "ARB", "OP", "INJ"]
DEFAULT_STOCK_UNIVERSE = ["AAPL", "MSFT", "NVDA", "TSLA", "META", "AMZN", "GOOGL", "AMD", "NFLX", "COIN"]
DEFAULT_FOREX_UNIVERSE = ["EUR_USD", "GBP_USD", "USD_JPY", "USD_CHF", "AUD_USD", "USD_CAD", "NZD_USD", "EUR_GBP", "EUR_JPY", "GBP_JPY"]
DEFAULT_FUTURES_UNIVERSE = ["ES", "NQ", "YM", "RTY", "CL", "GC", "SI", "NG", "ZB", "ZN"]

BROKER_ALIASES = {
    "ib": "interactive_brokers",
    "ibkr": "interactive_brokers",
    "interactivebroker": "interactive_brokers",
    "interactive_broker": "interactive_brokers",
    "interactive_brokers": "interactive_brokers",
    "interactive brokers": "interactive_brokers",
    "td": "schwab",
    "td_ameritrade": "schwab",
    "charles_schwab": "schwab",
    "tradestation": "tradestation",
    "trade_station": "tradestation",
}

BROKER_DEFAULT_ASSET_TYPE = {
    "binance": "crypto",
    "binanceus": "crypto",
    "kucoin": "crypto",
    "coinbase": "crypto",
    "kraken": "crypto",
    "bybit": "crypto",
    "okx": "crypto",
    "bitget": "crypto",
    "bitstamp": "crypto",
    "gateio": "crypto",
    "alpaca": "stock",
    "interactive_brokers": "stock",
    "ibkr": "stock",
    "schwab": "stock",
    "tradestation": "stock",
    "tastytrade": "stock",
    "robinhood": "stock",
    "webull": "stock",
    "fidelity": "stock",
    "etrade": "stock",
    "oanda": "forex",
    "fxcm": "forex",
    "forexcom": "forex",
    "paper": "crypto",
}

CCXT_EXCHANGE_BY_BROKER = {
    "binance": "binance",
    "binanceus": "binanceus",
    "kucoin": "kucoin",
    "coinbase": "coinbase",
    "kraken": "kraken",
    "bybit": "bybit",
    "okx": "okx",
    "bitget": "bitget",
    "bitstamp": "bitstamp",
    "gateio": "gateio",
    "paper": "binance",
}

POSITIVE_WORDS = ["surge", "gain", "bull", "beat", "rise", "growth", "profit", "strong", "up", "record", "upgrade", "rally", "breakout"]
NEGATIVE_WORDS = ["drop", "fall", "bear", "miss", "loss", "weak", "crash", "concern", "down", "downgrade", "lawsuit", "probe", "selloff"]
STABLE_OR_LEVERAGED = {"USDC", "FDUSD", "TUSD", "USDP", "DAI", "EUR", "TRY", "BUSD", "USTC"}
LEVERAGED_SUFFIXES = ("UP", "DOWN", "BULL", "BEAR", "3L", "3S", "5L", "5S")


def _clamp(x: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, x))


def _safe_float(x: Any, default: float = 0.0) -> float:
    try:
        if pd.isna(x):
            return default
        return float(x)
    except Exception:
        return default


def normalize_broker_id(broker_id: Optional[str]) -> str:
    raw = (broker_id or "paper").lower().strip().replace("-", "_")
    return BROKER_ALIASES.get(raw, raw)


def infer_asset_type_for_broker(broker_id: Optional[str], asset_type: Optional[str] = None) -> str:
    if asset_type:
        return asset_type
    return BROKER_DEFAULT_ASSET_TYPE.get(normalize_broker_id(broker_id), "crypto")


def _is_tradable_base(base: str) -> bool:
    base = base.upper()
    if base in STABLE_OR_LEVERAGED:
        return False
    if any(base.endswith(sfx) for sfx in LEVERAGED_SUFFIXES):
        return False
    return True


async def discover_crypto_universe(exchange_id: str = "binance", limit: int = 120, min_quote_volume_usdt: float = 2_000_000) -> List[str]:
    cached = await col_scan_cache.find_one({"kind": "crypto_universe", "exchange": exchange_id})
    if cached:
        ts = datetime.fromisoformat(cached.get("updated_at"))
        if datetime.utcnow() - ts < timedelta(hours=6):
            return cached.get("symbols", DEFAULT_CRYPTO_UNIVERSE)
    def _fetch_symbols():
        import ccxt
        ex_cls = getattr(ccxt, exchange_id, ccxt.binance)
        ex = ex_cls({"enableRateLimit": True})
        markets = ex.load_markets()
        tickers = ex.fetch_tickers()
        rows = []
        for symbol, market in markets.items():
            if not market.get("spot") or not market.get("active"):
                continue
            if market.get("quote") not in {"USDT", "USD"}:
                continue
            base = market.get("base", "").upper()
            if not _is_tradable_base(base):
                continue
            quote_volume = _safe_float((tickers.get(symbol, {}) or {}).get("quoteVolume"), 0)
            if quote_volume < min_quote_volume_usdt:
                continue
            rows.append((base, quote_volume))
        rows.sort(key=lambda x: x[1], reverse=True)
        out = []
        for base, _vol in rows:
            if base not in out:
                out.append(base)
            if len(out) >= limit:
                break
        return out or DEFAULT_CRYPTO_UNIVERSE
    try:
        loop = asyncio.get_event_loop()
        symbols = await loop.run_in_executor(None, _fetch_symbols)
    except Exception as e:
        log.warning(f"crypto universe discovery failed for {exchange_id}: {e}")
        symbols = DEFAULT_CRYPTO_UNIVERSE
    await col_scan_cache.replace_one({"kind": "crypto_universe", "exchange": exchange_id}, {"kind": "crypto_universe", "exchange": exchange_id, "symbols": symbols, "updated_at": datetime.utcnow().isoformat()}, upsert=True)
    return symbols


async def resolve_universe(universe: Optional[List[str]], asset_type: str, discover: bool = True, broker_id: Optional[str] = None) -> List[str]:
    if universe:
        return [s.upper().strip() for s in universe if s and isinstance(s, str)]
    broker = normalize_broker_id(broker_id)
    if asset_type == "crypto":
        exchange = CCXT_EXCHANGE_BY_BROKER.get(broker)
        if discover and exchange:
            return await discover_crypto_universe(exchange_id=exchange)
        return DEFAULT_CRYPTO_UNIVERSE
    if asset_type == "stock":
        return DEFAULT_STOCK_UNIVERSE
    if asset_type == "forex":
        return DEFAULT_FOREX_UNIVERSE
    if asset_type == "future":
        return DEFAULT_FUTURES_UNIVERSE
    return DEFAULT_CRYPTO_UNIVERSE


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
    return {"raw": raw, "score": round(_clamp(50 + raw * 8), 2), "sentiment": sentiment, "hits": hits[:10]}


async def fetch_news_sentiment(ticker: str) -> Dict[str, Any]:
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
        data = {"ticker": ticker.upper(), "headlines": headlines[:5], **_score_sentiment_from_headlines(headlines)}
    except Exception as e:
        data = {"ticker": ticker.upper(), "headlines": [], "raw": 0, "score": 50, "sentiment": "neutral", "error": str(e)}
    await col_scan_cache.replace_one({"kind": "news", "ticker": ticker.upper()}, {"kind": "news", "ticker": ticker.upper(), "data": data, "updated_at": datetime.utcnow().isoformat()}, upsert=True)
    return data


async def fetch_ai_sentiment(ticker: str, asset_type: str, enabled: bool = False) -> Dict[str, Any]:
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
        data = {"score": _clamp(50 + raw * 35), "raw": raw, "confidence": confidence, "reason": ai.get("reason", "AI sentiment")}
    except Exception as e:
        data = {"score": 50, "confidence": 0, "reason": f"AI unavailable: {e}"}
    await col_scan_cache.replace_one({"kind": "ai", "ticker": ticker.upper(), "asset_type": asset_type}, {"kind": "ai", "ticker": ticker.upper(), "asset_type": asset_type, "data": data, "updated_at": datetime.utcnow().isoformat()}, upsert=True)
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
        return {"ticker": ticker.upper(), "last_price": round(last, 6), "ret_1d_pct": round(ret_1d, 3), "ret_7d_pct": round(ret_7d, 3), "ret_30d_pct": round(ret_30d, 3), "volume_ratio": round(vol_ratio, 3), "atr_pct": round(atr_pct, 3), "momentum_score": round(_clamp(50 + ret_7d * 4 + ret_30d * 1.2), 2), "volume_score": round(_clamp(45 + (vol_ratio - 1) * 35), 2), "volatility_score": round(_clamp(100 - abs(atr_pct - 3.0) * 12), 2), "trend_score": round(_clamp(50 + ret_1d * 4 + ret_7d * 2), 2)}
    except Exception as e:
        log.warning(f"market feature scan failed for {ticker}: {e}")
        return {"ticker": ticker.upper(), "error": str(e), "score": 0}


async def fetch_intraday_spike_features(ticker: str, asset_type: str = "crypto", interval: str = "15m") -> Dict[str, Any]:
    end = datetime.utcnow()
    start = end - timedelta(days=7)
    try:
        df = await fetch_history(ticker, asset_type, start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d"), interval)
        if df is None or len(df) < 40:
            return {"ticker": ticker.upper(), "spike": False, "error": "insufficient intraday history"}
        close = df["close"].astype(float)
        volume = df["volume"].astype(float)
        high = df["high"].astype(float)
        low = df["low"].astype(float)
        last = _safe_float(close.iloc[-1])
        ret_1bar = (last / _safe_float(close.iloc[-2], last) - 1) * 100
        ret_4bar = (last / _safe_float(close.iloc[-5], last) - 1) * 100 if len(close) >= 5 else ret_1bar
        vol_ratio = _safe_float(volume.iloc[-1]) / max(_safe_float(volume.rolling(30).mean().iloc[-1], 1), 1)
        range_pct = _safe_float((high.iloc[-1] - low.iloc[-1]) / last * 100)
        spike_score = _clamp(50 + max(ret_4bar, 0) * 8 + (vol_ratio - 1) * 14 + range_pct * 4)
        spike = ret_4bar >= 2.0 and vol_ratio >= 1.8 and spike_score >= 70
        return {"ticker": ticker.upper(), "spike": spike, "spike_score": round(spike_score, 2), "ret_1bar_pct": round(ret_1bar, 3), "ret_4bar_pct": round(ret_4bar, 3), "volume_ratio": round(vol_ratio, 3), "range_pct": round(range_pct, 3), "last_price": round(last, 6), "interval": interval}
    except Exception as e:
        return {"ticker": ticker.upper(), "spike": False, "error": str(e)}


def _combine_scores(market: Dict[str, Any], news: Dict[str, Any], ai: Dict[str, Any]) -> Dict[str, Any]:
    if market.get("error"):
        return {"score": 0, "reason": market.get("error", "market error")}
    market_score = market.get("momentum_score", 50) * 0.35 + market.get("volume_score", 50) * 0.25 + market.get("volatility_score", 50) * 0.20 + market.get("trend_score", 50) * 0.20
    news_score = _safe_float(news.get("score", 50), 50)
    ai_score = _safe_float(ai.get("score", 50), 50)
    ai_weight = 0.10 if _safe_float(ai.get("confidence", 0)) >= 40 else 0.0
    news_weight = 0.15
    total = market_score * (1.0 - news_weight - ai_weight) + news_score * news_weight + ai_score * ai_weight
    reasons = [f"momentum {market.get('ret_7d_pct', 0)}%/7d", f"volume x{market.get('volume_ratio', 0)}", f"ATR {market.get('atr_pct', 0)}%", f"news {news.get('sentiment', 'neutral')} ({news.get('raw', 0)})"]
    if ai_weight:
        reasons.append(f"AI {ai.get('raw', 0)} conf {ai.get('confidence', 0)}")
    return {"score": round(_clamp(total), 2), "reason": "; ".join(reasons)}


async def score_symbol(ticker: str, asset_type: str = "crypto", interval: str = "1d", use_ai: bool = False) -> Dict[str, Any]:
    market, news, ai = await asyncio.gather(fetch_market_features(ticker, asset_type, interval), fetch_news_sentiment(ticker), fetch_ai_sentiment(ticker, asset_type, enabled=use_ai))
    combined = _combine_scores(market, news, ai)
    return {"ticker": ticker.upper(), "asset_type": asset_type, "score": combined["score"], "reason": combined["reason"], "market": market, "news": news, "ai": ai}


async def scan_universe(universe: Optional[List[str]] = None, asset_type: Optional[str] = None, interval: str = "1d", limit: int = 10, use_ai: bool = False, discover: bool = True, broker_id: Optional[str] = None) -> Dict[str, Any]:
    asset_type = infer_asset_type_for_broker(broker_id, asset_type)
    universe = await resolve_universe(universe, asset_type, discover=discover, broker_id=broker_id)
    results = await asyncio.gather(*[score_symbol(s, asset_type=asset_type, interval=interval, use_ai=use_ai) for s in universe], return_exceptions=True)
    ranked = [r for r in results if isinstance(r, dict)]
    ranked.sort(key=lambda x: x.get("score", 0), reverse=True)
    run = {"kind": "normal", "broker_id": normalize_broker_id(broker_id), "asset_type": asset_type, "interval": interval, "limit": limit, "use_ai": use_ai, "discover": discover, "universe_size": len(universe), "selected": ranked[:limit], "ranked": ranked, "created_at": datetime.utcnow().isoformat()}
    try:
        await col_scan_runs.insert_one(run)
    except Exception as e:
        log.debug(f"failed to store scan run: {e}")
    return {k: v for k, v in run.items() if k != "_id"}


async def scan_emergency_movers(universe: Optional[List[str]] = None, asset_type: Optional[str] = None, interval: str = "15m", limit: int = 5, use_ai: bool = False, discover: bool = True, broker_id: Optional[str] = None) -> Dict[str, Any]:
    asset_type = infer_asset_type_for_broker(broker_id, asset_type)
    universe = await resolve_universe(universe, asset_type, discover=discover, broker_id=broker_id)
    results = await asyncio.gather(*[fetch_intraday_spike_features(s, asset_type, interval) for s in universe], return_exceptions=True)
    movers = [r for r in results if isinstance(r, dict) and r.get("spike")]
    movers.sort(key=lambda x: x.get("spike_score", 0), reverse=True)
    enriched = []
    for m in movers[:limit]:
        ticker = m["ticker"]
        news, ai = await asyncio.gather(fetch_news_sentiment(ticker), fetch_ai_sentiment(ticker, asset_type, enabled=use_ai))
        sentiment_boost = (_safe_float(news.get("score", 50), 50) - 50) * 0.25
        ai_boost = (_safe_float(ai.get("score", 50), 50) - 50) * 0.10 if _safe_float(ai.get("confidence", 0)) >= 40 else 0
        final_score = _clamp(m.get("spike_score", 0) + sentiment_boost + ai_boost)
        enriched.append({**m, "asset_type": asset_type, "score": round(final_score, 2), "news": news, "ai": ai, "reason": f"sudden move {m.get('ret_4bar_pct')}%/{interval}; volume x{m.get('volume_ratio')}; news {news.get('sentiment')}"})
    enriched.sort(key=lambda x: x.get("score", 0), reverse=True)
    run = {"kind": "emergency", "broker_id": normalize_broker_id(broker_id), "asset_type": asset_type, "interval": interval, "limit": limit, "use_ai": use_ai, "discover": discover, "universe_size": len(universe), "selected": enriched[:limit], "ranked": enriched, "created_at": datetime.utcnow().isoformat()}
    try:
        await col_scan_runs.insert_one(run)
    except Exception as e:
        log.debug(f"failed to store emergency scan run: {e}")
    return {k: v for k, v in run.items() if k != "_id"}


async def update_dynamic_bot_watchlists(asset_type: Optional[str] = None, interval: str = "1d", limit: int = 10, use_ai: bool = False, discover: bool = True, broker_id: Optional[str] = None) -> Dict[str, Any]:
    query = {"use_dynamic_watchlist": True}
    if broker_id:
        query["broker"] = broker_id
    if asset_type:
        query["dynamic_asset_type"] = asset_type
    bots = await db["bots"].find(query).to_list(200)
    updated = 0
    results = []
    for bot in bots:
        bot_broker = bot.get("broker", broker_id or "paper")
        bot_asset = infer_asset_type_for_broker(bot_broker, bot.get("dynamic_asset_type") or asset_type)
        bot_limit = int(bot.get("dynamic_max_watchlist", limit) or limit)
        scan = await scan_universe(asset_type=bot_asset, interval=interval, limit=bot_limit, use_ai=use_ai, discover=discover, broker_id=bot_broker)
        watchlist = [{"ticker": x["ticker"], "asset_type": x.get("asset_type", bot_asset)} for x in scan["selected"]]
        await db["bots"].update_one({"_id": bot["_id"]}, {"$set": {"watchlist": watchlist, "last_watchlist_scan_at": datetime.utcnow().isoformat(), "last_watchlist_scan_score": [{"ticker": x["ticker"], "score": x["score"], "reason": x["reason"]} for x in scan["selected"]]}})
        updated += 1
        results.append({"bot_id": str(bot["_id"]), "broker": bot_broker, "asset_type": bot_asset, "watchlist": watchlist})
    return {"updated_bots": updated, "results": results}


async def promote_emergency_movers(asset_type: Optional[str] = None, interval: str = "15m", limit: int = 3, use_ai: bool = False, min_score: float = 75, discover: bool = True, broker_id: Optional[str] = None) -> Dict[str, Any]:
    query = {"use_dynamic_watchlist": True}
    if broker_id:
        query["broker"] = broker_id
    if asset_type:
        query["dynamic_asset_type"] = asset_type
    bots = await db["bots"].find(query).to_list(200)
    updated = 0
    results = []
    for bot in bots:
        bot_broker = bot.get("broker", broker_id or "paper")
        bot_asset = infer_asset_type_for_broker(bot_broker, bot.get("dynamic_asset_type") or asset_type)
        scan = await scan_emergency_movers(asset_type=bot_asset, interval=interval, limit=limit, use_ai=use_ai, discover=discover, broker_id=bot_broker)
        movers = [x for x in scan["selected"] if x.get("score", 0) >= min_score]
        current = bot.get("watchlist", []) or []
        seen = {x.get("ticker", "").upper() for x in current}
        additions = [{"ticker": m["ticker"], "asset_type": bot_asset} for m in movers if m["ticker"] not in seen]
        if not additions:
            results.append({"bot_id": str(bot["_id"]), "broker": bot_broker, "asset_type": bot_asset, "added": []})
            continue
        max_len = int(bot.get("dynamic_max_watchlist", 10) or 10)
        new_watchlist = (additions + current)[:max_len]
        await db["bots"].update_one({"_id": bot["_id"]}, {"$set": {"watchlist": new_watchlist, "last_emergency_scan_at": datetime.utcnow().isoformat(), "last_emergency_movers": [{"ticker": m["ticker"], "score": m["score"], "reason": m["reason"]} for m in movers]}})
        updated += 1
        results.append({"bot_id": str(bot["_id"]), "broker": bot_broker, "asset_type": bot_asset, "added": additions})
    return {"updated_bots": updated, "results": results}
