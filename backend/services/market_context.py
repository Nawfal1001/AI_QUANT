"""Automatic market-context scoring for confidence calibration.

Adds cross-timeframe, correlation, and crypto derivatives context without
changing base strategy signals. Designed to be consumed by signals/bots as a
confidence adjustment layer.
"""
import asyncio
from functools import partial
from typing import Dict, List

import ccxt
import numpy as np
import pandas as pd
import yfinance as yf

from services.logger import child

log = child("market_context")

CRYPTO_BENCHMARKS = ["BTC", "ETH", "BNB", "SOL"]
FOREX_BENCHMARKS = ["EURUSD=X", "GBPUSD=X", "USDJPY=X", "AUDUSD=X", "USDCAD=X"]


def _ema(arr, period):
    if len(arr) == 0:
        return 0.0
    k = 2 / (period + 1)
    e = float(arr[0])
    for x in arr[1:]:
        e = float(x) * k + e * (1 - k)
    return float(e)


def _signal_from_df(df: pd.DataFrame) -> Dict:
    if df is None or df.empty or len(df) < 30:
        return {"direction": "neutral", "score": 0, "reason": "insufficient_data"}
    closes = df["close"].astype(float).values
    volumes = df.get("volume", pd.Series([0] * len(df))).astype(float).values
    close = float(closes[-1])
    ema20 = _ema(closes[-40:], 20)
    ema50 = _ema(closes[-80:], 50) if len(closes) >= 80 else _ema(closes[-50:], 50)
    ema50_prev = _ema(closes[-100:-20], 50) if len(closes) >= 100 else ema50
    vol_avg = float(np.mean(volumes[-20:])) if len(volumes) >= 20 else max(float(volumes[-1]), 1)
    vol_ratio = float(volumes[-1]) / max(vol_avg, 1e-9)

    score = 0
    if close > ema20 > ema50:
        score += 1
    if close < ema20 < ema50:
        score -= 1
    if ema50 > ema50_prev:
        score += 1
    if ema50 < ema50_prev:
        score -= 1
    if vol_ratio >= 1.2:
        score += 1 if score > 0 else -1 if score < 0 else 0

    if score >= 2:
        return {"direction": "bullish", "score": score, "close": close, "ema20": ema20, "ema50": ema50, "vol_ratio": round(vol_ratio, 3)}
    if score <= -2:
        return {"direction": "bearish", "score": score, "close": close, "ema20": ema20, "ema50": ema50, "vol_ratio": round(vol_ratio, 3)}
    return {"direction": "neutral", "score": score, "close": close, "ema20": ema20, "ema50": ema50, "vol_ratio": round(vol_ratio, 3)}


def _crypto_ohlcv(symbol: str, timeframe: str, limit: int = 120) -> pd.DataFrame:
    ex = ccxt.binance({"enableRateLimit": True})
    data = ex.fetch_ohlcv(f"{symbol.upper()}/USDT", timeframe=timeframe, limit=limit)
    return pd.DataFrame(data, columns=["ts", "open", "high", "low", "close", "volume"])


def _stock_or_forex_history(ticker: str, interval: str, period: str = "60d") -> pd.DataFrame:
    hist = yf.Ticker(ticker).history(period=period, interval=interval)
    if hist.empty:
        return pd.DataFrame()
    hist = hist.rename(columns={"Open": "open", "High": "high", "Low": "low", "Close": "close", "Volume": "volume"})
    if "volume" not in hist:
        hist["volume"] = 0
    return hist[["open", "high", "low", "close", "volume"]].dropna()


def _multi_timeframe(symbol: str, asset_type: str) -> Dict:
    if asset_type == "crypto":
        frames = {"1m": _crypto_ohlcv(symbol, "1m"), "5m": _crypto_ohlcv(symbol, "5m"), "15m": _crypto_ohlcv(symbol, "15m")}
    else:
        ticker = symbol if asset_type != "forex" else (symbol if "=" in symbol else f"{symbol}=X")
        frames = {"15m": _stock_or_forex_history(ticker, "15m"), "1h": _stock_or_forex_history(ticker, "1h"), "1d": _stock_or_forex_history(ticker, "1d", "1y")}
    analysis = {tf: _signal_from_df(df) for tf, df in frames.items()}
    bull = sum(1 for v in analysis.values() if v["direction"] == "bullish")
    bear = sum(1 for v in analysis.values() if v["direction"] == "bearish")
    if bull >= 2:
        consensus = "bullish"
    elif bear >= 2:
        consensus = "bearish"
    else:
        consensus = "mixed"
    return {"consensus": consensus, "frames": analysis}


def _correlation_context(symbol: str, asset_type: str) -> Dict:
    if asset_type == "crypto":
        ex = ccxt.binance({"enableRateLimit": True})
        target = _crypto_ohlcv(symbol, "1h", 200)["close"].pct_change().dropna()
        benchmarks = [b for b in CRYPTO_BENCHMARKS if b.upper() != symbol.upper()]
        cors = {}
        for b in benchmarks:
            try:
                ret = _crypto_ohlcv(b, "1h", 200)["close"].pct_change().dropna()
                n = min(len(target), len(ret))
                cors[b] = round(float(np.corrcoef(target.tail(n), ret.tail(n))[0, 1]), 4) if n > 20 else 0
            except Exception as e:
                log.debug(f"correlation failed {symbol}/{b}: {e}")
        return {"benchmarks": cors}

    ticker = symbol if asset_type != "forex" else (symbol if "=" in symbol else f"{symbol}=X")
    target_df = _stock_or_forex_history(ticker, "1d", "1y")
    target = target_df["close"].pct_change().dropna() if not target_df.empty else pd.Series(dtype=float)
    cors = {}
    for b in FOREX_BENCHMARKS:
        if b == ticker:
            continue
        try:
            df = _stock_or_forex_history(b, "1d", "1y")
            ret = df["close"].pct_change().dropna()
            n = min(len(target), len(ret))
            cors[b] = round(float(np.corrcoef(target.tail(n), ret.tail(n))[0, 1]), 4) if n > 20 else 0
        except Exception as e:
            log.debug(f"forex correlation failed {ticker}/{b}: {e}")
    return {"benchmarks": cors}


def _crypto_derivatives(symbol: str) -> Dict:
    ex = ccxt.binance({"enableRateLimit": True, "options": {"defaultType": "future"}})
    pair = f"{symbol.upper()}/USDT"
    out = {"funding_rate": None, "open_interest": None, "orderbook_imbalance": None}
    try:
        funding = ex.fetch_funding_rate(pair)
        out["funding_rate"] = funding.get("fundingRate")
    except Exception as e:
        log.debug(f"funding unavailable {symbol}: {e}")
    try:
        oi = ex.fetch_open_interest(pair)
        out["open_interest"] = oi.get("openInterestAmount") or oi.get("openInterestValue")
    except Exception as e:
        log.debug(f"open interest unavailable {symbol}: {e}")
    try:
        ob = ex.fetch_order_book(pair, limit=20)
        bid = sum(float(p) * float(q) for p, q in ob.get("bids", []))
        ask = sum(float(p) * float(q) for p, q in ob.get("asks", []))
        out["orderbook_imbalance"] = round((bid - ask) / max(bid + ask, 1e-9), 4)
    except Exception as e:
        log.debug(f"orderbook unavailable {symbol}: {e}")
    return out


def _score_context(symbol: str, asset_type: str) -> Dict:
    mtf = _multi_timeframe(symbol, asset_type)
    corr = _correlation_context(symbol, asset_type)
    deriv = _crypto_derivatives(symbol) if asset_type == "crypto" else {}

    confidence_adjustment = 0
    if mtf["consensus"] in ("bullish", "bearish"):
        confidence_adjustment += 8
    else:
        confidence_adjustment -= 4

    high_corr = [k for k, v in corr.get("benchmarks", {}).items() if abs(v) >= 0.7]
    if high_corr:
        confidence_adjustment += 3

    if asset_type == "crypto":
        imb = deriv.get("orderbook_imbalance")
        if imb is not None and abs(imb) >= 0.12:
            confidence_adjustment += 4
        funding = deriv.get("funding_rate")
        if funding is not None and abs(float(funding)) > 0.001:
            confidence_adjustment -= 3

    return {
        "symbol": symbol.upper(),
        "asset_type": asset_type,
        "confidence_adjustment": max(-15, min(15, confidence_adjustment)),
        "multi_timeframe": mtf,
        "correlation": corr,
        "derivatives": deriv,
    }


async def market_context(symbol: str, asset_type: str = "crypto") -> Dict:
    return await asyncio.get_event_loop().run_in_executor(None, partial(_score_context, symbol.upper(), asset_type.lower()))
