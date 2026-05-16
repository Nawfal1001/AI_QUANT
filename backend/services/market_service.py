"""
Market data service.

Live quotes / history / movers / search. Yahoo Finance is the primary source;
when it's rate-limited or returns empty we fall back to Alpha Vantage via the
helper already used by the backtest engine.
"""
import asyncio
from functools import partial

import ccxt
import pandas as pd
import yfinance as yf

from services.backtest_engine import _fetch_alpha_vantage_stock_history
from services.logger import child as _child_log

_log = _child_log('market_service')


def _normalize_history(hist):
    if hist is None or len(hist) == 0:
        return None
    df = hist.reset_index() if any(c in hist.columns for c in ["Date", "Datetime"]) is False else hist.copy()
    if "Date" in df.columns:
        df = df.rename(columns={"Date": "date"})
    elif "Datetime" in df.columns:
        df = df.rename(columns={"Datetime": "date"})
    df = df.rename(columns={"Open": "open", "High": "high", "Low": "low", "Close": "close", "Volume": "volume"})
    return df.dropna(subset=["close"])


def _stock(ticker, rng):
    pm = {"1d": "1d", "5d": "5d", "1mo": "1mo", "3mo": "3mo", "6mo": "6mo", "1y": "1y"}
    period = pm.get(rng, "1mo")
    hist = None
    info = {}
    try:
        t = yf.Ticker(ticker)
        info = t.info or {}
        hist = t.history(period=period, interval="1d")
        if hist is None or hist.empty:
            hist = None
    except Exception as e:
        _log.warning(f"yfinance failed for {ticker}: {e}")

    # Fallback to Alpha Vantage if yfinance gave us nothing
    if hist is None or len(hist) == 0:
        from datetime import datetime, timedelta
        days = {"1d": 2, "5d": 8, "1mo": 35, "3mo": 95, "6mo": 190, "1y": 380}.get(period, 35)
        end = datetime.utcnow().strftime("%Y-%m-%d")
        start = (datetime.utcnow() - timedelta(days=days)).strftime("%Y-%m-%d")
        av = _fetch_alpha_vantage_stock_history(ticker, start, end, "1d")
        if av is None or len(av) == 0:
            return {"error": "No data", "ticker": ticker}
        df = av.tail(days)
        df = df.rename(columns={"date": "date"})
    else:
        df = _normalize_history(hist)
        if df is None:
            return {"error": "No data", "ticker": ticker}

    df["date"] = df["date"].astype(str)
    p = float(df["close"].iloc[-1])
    pp = float(df["close"].iloc[-2]) if len(df) > 1 else p
    return {
        "ticker": ticker, "name": info.get("longName", ticker),
        "price": round(p, 2),
        "change": round(p - pp, 2),
        "change_pct": round((p - pp) / pp * 100, 2) if pp else 0,
        "volume": int(df["volume"].iloc[-1]) if "volume" in df.columns else 0,
        "market_cap": info.get("marketCap", 0),
        "sector": info.get("sector", ""),
        "pe_ratio": info.get("trailingPE", None),
        "history": [
            {"date": r["date"], "open": round(float(r["open"]), 2), "high": round(float(r["high"]), 2),
             "low": round(float(r["low"]), 2), "close": round(float(r["close"]), 2),
             "volume": int(float(r.get("volume", 0) or 0))}
            for _, r in df.iterrows()
        ],
    }


def _crypto(symbol, rng):
    lm = {"1d": 1, "5d": 5, "1mo": 30, "3mo": 90, "6mo": 180, "1y": 365}
    ex = ccxt.binance({"enableRateLimit": True})
    try:
        ohlcv = ex.fetch_ohlcv(f"{symbol}/USDT", "1d", limit=lm.get(rng, 30) + 2)
        df = pd.DataFrame(ohlcv, columns=["ts", "open", "high", "low", "close", "volume"])
        t = ex.fetch_ticker(f"{symbol}/USDT")
        return {
            "ticker": symbol,
            "price": round(t["last"], 4),
            "change": round(t.get("change", 0) or 0, 4),
            "change_pct": round(t.get("percentage", 0) or 0, 2),
            "volume": round(t.get("quoteVolume", 0) or 0, 2),
            "history": [
                {"date": str(pd.Timestamp(r["ts"], unit="ms").date()),
                 "open": round(r["open"], 4), "high": round(r["high"], 4),
                 "low": round(r["low"], 4), "close": round(r["close"], 4),
                 "volume": round(r["volume"], 2)}
                for _, r in df.iterrows()
            ],
        }
    except Exception as e:
        _log.warning(f"crypto fetch failed for {symbol}: {e}")
        return {"error": str(e), "ticker": symbol}


def _movers():
    """Top-movers across a curated stock list + top crypto pairs.

    yfinance is fetched in ONE batched call (used to be 12 sequential `.info`
    requests — minutes of latency). ccxt batch-fetches all crypto tickers in one
    call as before.
    """
    stocks = ["AAPL", "NVDA", "TSLA", "MSFT", "AMZN", "META", "GOOGL", "AMD", "NFLX", "INTC", "BABA", "ORCL"]
    movers = []

    # Batched 2-day daily bars — gives us latest close + previous close for change_pct
    try:
        data = yf.download(" ".join(stocks), period="2d", interval="1d", group_by="ticker", progress=False, threads=True, auto_adjust=False)
        for t in stocks:
            try:
                col = data[t] if t in getattr(data, "columns", {}).get_level_values(0) else None
                if col is None:
                    continue
                closes = col["Close"].dropna()
                if len(closes) < 1:
                    continue
                last = float(closes.iloc[-1])
                prev = float(closes.iloc[-2]) if len(closes) >= 2 else last
                pct = (last - prev) / prev * 100 if prev else 0
                movers.append({"ticker": t, "name": t, "price": round(last, 2), "change_pct": round(pct, 2), "type": "stock"})
            except Exception as e:
                _log.debug(f"mover parse failed for {t}: {e}")
    except Exception as e:
        _log.warning(f"yfinance batch movers failed: {e}")

    try:
        ex = ccxt.binance({"enableRateLimit": True})
        pairs = ["BTC/USDT", "ETH/USDT", "BNB/USDT", "SOL/USDT", "ADA/USDT", "XRP/USDT", "DOGE/USDT"]
        td = ex.fetch_tickers(pairs)
        for p, d in td.items():
            s = p.replace("/USDT", "")
            movers.append({
                "ticker": s, "name": s,
                "price": round(d.get("last", 0), 4),
                "change_pct": round(d.get("percentage", 0) or 0, 2),
                "type": "crypto",
            })
    except Exception as e:
        _log.warning(f"crypto movers fetch failed: {e}")

    movers.sort(key=lambda x: abs(x.get("change_pct", 0)), reverse=True)
    return movers[:20]


async def get_stock(ticker, rng="1mo"):
    return await asyncio.get_event_loop().run_in_executor(None, partial(_stock, ticker.upper(), rng))


async def get_crypto(symbol, rng="1mo"):
    return await asyncio.get_event_loop().run_in_executor(None, partial(_crypto, symbol.upper(), rng))


async def get_movers(atype="all"):
    return await asyncio.get_event_loop().run_in_executor(None, _movers)


async def search(q):
    res = []
    try:
        i = yf.Ticker(q.upper()).info
        if i.get("longName"):
            res.append({"ticker": q.upper(), "name": i["longName"], "type": "stock"})
    except Exception as e:
        _log.debug(f"search yf failed for {q}: {e}")
    for c in ["BTC", "ETH", "BNB", "SOL", "ADA", "XRP", "DOGE", "AVAX", "MATIC", "DOT"]:
        if q.upper() in c:
            res.append({"ticker": c, "name": c, "type": "crypto"})
    return res[:10]
