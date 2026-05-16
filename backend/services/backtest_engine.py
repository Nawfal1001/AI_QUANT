"""
Backtest Engine v2.1 — shared multi-asset OHLCV fetcher.
Supports stocks, crypto, forex, gold, oil and common broker/CFD aliases.
"""
import asyncio
import math
import os
from datetime import datetime, timedelta
from functools import partial

import numpy as np
import pandas as pd

from services.strategies import STRATEGIES
from services.logger import child

log = child("backtest")
DEFAULT_FEE_BPS = 5
DEFAULT_SLIPPAGE_BPS = 3
DEFAULT_SPREAD_BPS = 2
_HISTORY_CACHE = {}

YAHOO_SPECIAL = {
    "XAUUSD": "GC=F", "XAU_USD": "GC=F", "GOLD": "GC=F", "GC": "GC=F", "GC=F": "GC=F",
    "XAGUSD": "SI=F", "XAG_USD": "SI=F", "SILVER": "SI=F", "SI": "SI=F", "SI=F": "SI=F",
    "OIL": "CL=F", "WTI": "CL=F", "CL": "CL=F", "CL=F": "CL=F",
    "BRENT": "BZ=F", "BZ": "BZ=F", "BZ=F": "BZ=F",
}
USD_BASE_YAHOO = {"USD_JPY": "JPY=X", "USDJPY": "JPY=X", "USD_CHF": "CHF=X", "USDCHF": "CHF=X", "USD_CAD": "CAD=X", "USDCAD": "CAD=X", "USD_MXN": "MXN=X", "USDMXN": "MXN=X"}


def _cache_key(ticker, asset_type, start, end, interval):
    return f"{asset_type}:{str(ticker).upper()}:{start}:{end}:{interval}"


def _to_yahoo_symbol(ticker, asset_type="stock"):
    raw = str(ticker or "").upper().strip().replace("/", "_").replace("-", "_").replace(" ", "")
    raw = raw.replace(".FX", "").replace(".FOREX", "")
    if raw in YAHOO_SPECIAL:
        return YAHOO_SPECIAL[raw]
    if asset_type in {"forex", "fx"} or "_" in raw and len(raw.replace("_", "")) == 6:
        if raw in USD_BASE_YAHOO:
            return USD_BASE_YAHOO[raw]
        pair = raw.replace("_", "")
        if len(pair) == 6:
            return f"{pair}=X"
    return raw


def _normalize_history_frame(hist):
    if hist is None or len(hist) == 0:
        return None
    hist = hist.copy()
    if isinstance(hist.columns, pd.MultiIndex):
        hist.columns = [c[0] if isinstance(c, tuple) else c for c in hist.columns]
    if "Date" not in hist.columns and "Datetime" not in hist.columns and "date" not in hist.columns:
        hist = hist.reset_index()
    cols = {str(c).lower().replace(" ", "_"): c for c in hist.columns}
    date_col = cols.get("date") or cols.get("datetime") or cols.get("index")
    open_col = cols.get("open")
    high_col = cols.get("high")
    low_col = cols.get("low")
    close_col = cols.get("close") or cols.get("adj_close") or cols.get("adjusted_close")
    volume_col = cols.get("volume")
    if not all([date_col, open_col, high_col, low_col, close_col]):
        log.warning(f"history frame missing OHLC columns: {list(hist.columns)}")
        return None
    out = pd.DataFrame({
        "date": pd.to_datetime(hist[date_col], errors="coerce"),
        "open": pd.to_numeric(hist[open_col], errors="coerce"),
        "high": pd.to_numeric(hist[high_col], errors="coerce"),
        "low": pd.to_numeric(hist[low_col], errors="coerce"),
        "close": pd.to_numeric(hist[close_col], errors="coerce"),
        "volume": pd.to_numeric(hist[volume_col], errors="coerce") if volume_col else 0,
    }).dropna(subset=["date", "open", "high", "low", "close"])
    return out.sort_values("date") if len(out) else None


def _fetch_yahoo_history(symbol, start, end, interval="1d"):
    try:
        import yfinance as yf
        hist = yf.download(symbol, start=start, end=end, interval=interval, progress=False, auto_adjust=False, threads=False)
        df = _normalize_history_frame(hist)
        if df is not None and len(df) > 0:
            return df
        hist = yf.Ticker(symbol).history(start=start, end=end, interval=interval, auto_adjust=False, raise_errors=False)
        df = _normalize_history_frame(hist)
        if df is not None and len(df) > 0:
            return df
        log.warning(f"Yahoo returned 0 candles for {symbol}")
        return None
    except Exception as e:
        log.warning(f"Yahoo fetch failed for {symbol}: {e}")
        return None


def _fetch_alpha_vantage_stock_history(ticker, start, end, interval="1d"):
    key = (os.getenv("ALPHA_VANTAGE_API_KEY") or os.getenv("ALPHAVANTAGE_API_KEY") or "").strip()
    if not key:
        log.warning("Alpha Vantage fallback unavailable: ALPHA_VANTAGE_API_KEY missing")
        return None
    try:
        import httpx
        is_daily = interval in {"1d", "1D", "day", "daily"}
        if is_daily:
            params = {"function": "TIME_SERIES_DAILY_ADJUSTED", "symbol": ticker, "outputsize": "full", "apikey": key}
            time_key = "Time Series (Daily)"
        else:
            av_interval = interval if interval in {"1min", "5min", "15min", "30min", "60min"} else "15min"
            params = {"function": "TIME_SERIES_INTRADAY", "symbol": ticker, "interval": av_interval, "outputsize": "full", "apikey": key}
            time_key = f"Time Series ({av_interval})"
        r = httpx.get("https://www.alphavantage.co/query", params=params, timeout=20)
        r.raise_for_status()
        data = r.json()
        series = data.get(time_key) or {}
        if not series:
            msg = data.get("Note") or data.get("Information") or data.get("Error Message") or data.get("message") or "empty response"
            log.warning(f"Alpha Vantage returned no history for {ticker}: {msg}")
            return None
        rows = []
        start_ts = pd.Timestamp(start).tz_localize(None)
        end_ts = pd.Timestamp(end).tz_localize(None) + pd.Timedelta(days=1)
        for dt, vals in series.items():
            ts = pd.Timestamp(dt).tz_localize(None)
            if ts < start_ts or ts > end_ts:
                continue
            rows.append({"date": ts, "open": vals.get("1. open"), "high": vals.get("2. high"), "low": vals.get("3. low"), "close": vals.get("4. close") or vals.get("5. adjusted close"), "volume": vals.get("6. volume") or vals.get("5. volume") or 0})
        return _normalize_history_frame(pd.DataFrame(rows)) if rows else None
    except Exception as e:
        log.warning(f"Alpha Vantage stock history fallback failed for {ticker}: {e}")
        return None


def _fetch_stock_history(ticker, start, end, interval="1d"):
    symbol = _to_yahoo_symbol(ticker, "stock")
    return _fetch_yahoo_history(symbol, start, end, interval) or _fetch_alpha_vantage_stock_history(symbol, start, end, interval)


def _fetch_yahoo_asset_history(ticker, asset_type, start, end, interval="1d"):
    symbol = _to_yahoo_symbol(ticker, asset_type)
    return _fetch_yahoo_history(symbol, start, end, interval)


def _fetch_crypto_history(symbol, start, end, interval="1d"):
    try:
        import ccxt
        ex = ccxt.binance({"enableRateLimit": True})
        tf_map = {"1m": "1m", "5m": "5m", "15m": "15m", "30m": "30m", "1d": "1d", "4h": "4h", "1h": "1h"}
        tf = tf_map.get(interval, "1d")
        base = str(symbol).upper().replace("/USDT", "").replace("USDT", "").replace("_USDT", "")
        pair = f"{base}/USDT"
        since_ms = int(pd.Timestamp(start).timestamp() * 1000)
        end_ms = int(pd.Timestamp(end).timestamp() * 1000)
        all_bars = []
        cursor = since_ms
        while cursor < end_ms:
            bars = ex.fetch_ohlcv(pair, tf, since=cursor, limit=1000)
            if not bars:
                break
            all_bars.extend(bars)
            cursor = bars[-1][0] + 1
            if len(bars) < 1000:
                break
        if not all_bars:
            log.warning(f"ccxt returned 0 candles for {pair}")
            return None
        df = pd.DataFrame(all_bars, columns=["ts", "open", "high", "low", "close", "volume"])
        df["date"] = pd.to_datetime(df["ts"], unit="ms")
        df = df[df["date"] <= pd.Timestamp(end)]
        return df[["date", "open", "high", "low", "close", "volume"]]
    except Exception as e:
        log.warning(f"ccxt fetch failed for {symbol}: {e}")
        return None


async def fetch_history(ticker, asset_type, start, end, interval="1d"):
    at = str(asset_type or "stock").lower()
    key = _cache_key(ticker, at, start, end, interval)
    cached = _HISTORY_CACHE.get(key)
    now = datetime.utcnow().timestamp()
    if cached and now - cached["ts"] < 900:
        return cached["df"].copy() if cached["df"] is not None else None
    loop = asyncio.get_event_loop()
    if at == "crypto":
        df = await loop.run_in_executor(None, partial(_fetch_crypto_history, ticker, start, end, interval))
    elif at in {"forex", "fx", "gold", "oil", "metal", "metals", "commodity", "future", "futures"}:
        df = await loop.run_in_executor(None, partial(_fetch_yahoo_asset_history, ticker, at, start, end, interval))
    else:
        df = await loop.run_in_executor(None, partial(_fetch_stock_history, ticker, start, end, interval))
    _HISTORY_CACHE[key] = {"ts": now, "df": df.copy() if df is not None else None}
    return df


def _apply_costs(price, side, fee_bps, slip_bps, spread_bps):
    cost_pct = (slip_bps + spread_bps) / 10000
    fee_pct = fee_bps / 10000
    return price * (1 + cost_pct) * (1 + fee_pct) if side == "BUY" else price * (1 - cost_pct) * (1 - fee_pct)


async def run_backtest(ticker: str, asset_type: str = "stock", start_date: str = None, end_date: str = None, interval: str = "1d", initial_capital: float = 10000, risk_per_trade: float = 0.02, min_confidence: int = 55, sl_atr_mult: float = 2.0, tp_atr_mult: float = 3.0, fee_bps: float = DEFAULT_FEE_BPS, slippage_bps: float = DEFAULT_SLIPPAGE_BPS, spread_bps: float = DEFAULT_SPREAD_BPS, max_hold_bars: int = 30, strategy: str = "ensemble", custom_strategy_def: dict = None):
    if custom_strategy_def is not None:
        from services.custom_strategy import run_custom_strategy
        strategy_name = custom_strategy_def.get("name", "custom")
        def signal_fn(window): return run_custom_strategy(custom_strategy_def, window)
    else:
        if strategy not in STRATEGIES:
            return {"error": f"Unknown strategy: {strategy}. Available: {list(STRATEGIES.keys())}"}
        signal_fn = STRATEGIES[strategy]
        strategy_name = strategy
    if not end_date: end_date = datetime.now().strftime("%Y-%m-%d")
    if not start_date: start_date = (datetime.now() - timedelta(days=365)).strftime("%Y-%m-%d")
    df = await fetch_history(ticker, asset_type, start_date, end_date, interval)
    if df is None or len(df) < 60:
        return {"error": f"Insufficient history for {ticker}", "bars": 0 if df is None else len(df)}
    capital = initial_capital
    equity_curve = [{"date": str(df["date"].iloc[0])[:10], "equity": capital}]
    drawdown_curve = [{"date": str(df["date"].iloc[0])[:10], "dd_pct": 0}]
    trades = []; open_position = None; bars_since_entry = 0; peak_equity = capital
    for i in range(50, len(df)):
        row = df.iloc[i]; sig_window = df.iloc[max(0, i - 50):i]; sig = signal_fn(sig_window)
        price = float(row["close"]); high = float(row["high"]); low = float(row["low"]); atr = price * (sig.get("atr_pct", 1) / 100)
        if open_position:
            bars_since_entry += 1; exit_reason = None; exit_price = None
            if open_position["side"] == "BUY":
                if low <= open_position["sl"]: exit_price, exit_reason = open_position["sl"], "SL"
                elif high >= open_position["tp"]: exit_price, exit_reason = open_position["tp"], "TP"
                elif bars_since_entry >= max_hold_bars: exit_price, exit_reason = price, "TIME"
            else:
                if high >= open_position["sl"]: exit_price, exit_reason = open_position["sl"], "SL"
                elif low <= open_position["tp"]: exit_price, exit_reason = open_position["tp"], "TP"
                elif bars_since_entry >= max_hold_bars: exit_price, exit_reason = price, "TIME"
            if not exit_reason and sig["confidence"] >= min_confidence:
                if open_position["side"] == "BUY" and "SELL" in sig["signal"]: exit_price, exit_reason = price, "REVERSAL"
                elif open_position["side"] == "SELL" and "BUY" in sig["signal"]: exit_price, exit_reason = price, "REVERSAL"
            if exit_reason:
                exec_exit = _apply_costs(exit_price, "SELL" if open_position["side"] == "BUY" else "BUY", fee_bps, slippage_bps, spread_bps)
                pnl = (exec_exit - open_position["entry_price_net"]) * open_position["qty"] if open_position["side"] == "BUY" else (open_position["entry_price_net"] - exec_exit) * open_position["qty"]
                capital += pnl
                trades.append({"entry_date": open_position["entry_date"], "exit_date": str(row["date"])[:10], "side": open_position["side"], "entry_price": round(open_position["entry_price_net"], 4), "exit_price": round(exec_exit, 4), "qty": round(open_position["qty"], 4), "pnl": round(pnl, 2), "pnl_pct": round(pnl / (open_position["entry_price_net"] * open_position["qty"]) * 100, 2), "exit_reason": exit_reason, "bars_held": bars_since_entry, "confidence": open_position.get("confidence")})
                open_position = None; bars_since_entry = 0
        if not open_position and sig["confidence"] >= min_confidence and "HOLD" not in sig["signal"]:
            side = "BUY" if "BUY" in sig["signal"] else "SELL"; risk_dollars = capital * risk_per_trade; stop_distance = max(atr * sl_atr_mult, price * 0.005); qty = risk_dollars / stop_distance; entry_price_net = _apply_costs(price, side, fee_bps, slippage_bps, spread_bps); sl = price - stop_distance if side == "BUY" else price + stop_distance; tp = price + atr * tp_atr_mult if side == "BUY" else price - atr * tp_atr_mult
            open_position = {"side": side, "entry_price": price, "entry_price_net": entry_price_net, "qty": qty, "sl": sl, "tp": tp, "entry_date": str(row["date"])[:10], "confidence": sig["confidence"]}; bars_since_entry = 0
        equity = capital
        if open_position: equity += (price - open_position["entry_price_net"]) * open_position["qty"] if open_position["side"] == "BUY" else (open_position["entry_price_net"] - price) * open_position["qty"]
        peak_equity = max(peak_equity, equity); dd_pct = (equity - peak_equity) / peak_equity * 100 if peak_equity > 0 else 0
        equity_curve.append({"date": str(row["date"])[:10], "equity": round(equity, 2)}); drawdown_curve.append({"date": str(row["date"])[:10], "dd_pct": round(dd_pct, 2)})
    if open_position:
        last_price = float(df["close"].iloc[-1]); exec_exit = _apply_costs(last_price, "SELL" if open_position["side"] == "BUY" else "BUY", fee_bps, slippage_bps, spread_bps); pnl = (exec_exit - open_position["entry_price_net"]) * open_position["qty"] if open_position["side"] == "BUY" else (open_position["entry_price_net"] - exec_exit) * open_position["qty"]; capital += pnl
        trades.append({"entry_date": open_position["entry_date"], "exit_date": str(df["date"].iloc[-1])[:10], "side": open_position["side"], "entry_price": round(open_position["entry_price_net"], 4), "exit_price": round(exec_exit, 4), "qty": round(open_position["qty"], 4), "pnl": round(pnl, 2), "pnl_pct": round(pnl / (open_position["entry_price_net"] * open_position["qty"]) * 100, 2), "exit_reason": "EOT", "bars_held": bars_since_entry, "confidence": open_position.get("confidence")})
    wins = [t for t in trades if t["pnl"] > 0]; losses = [t for t in trades if t["pnl"] <= 0]; total = len(trades); win_rate = len(wins) / total * 100 if total else 0; gross_profit = sum(t["pnl"] for t in wins); gross_loss = abs(sum(t["pnl"] for t in losses)); profit_factor = gross_profit / gross_loss if gross_loss > 0 else (gross_profit if gross_profit else 0); avg_win = gross_profit / len(wins) if wins else 0; avg_loss = gross_loss / len(losses) if losses else 0; expectancy = (win_rate / 100) * avg_win - (1 - win_rate / 100) * avg_loss
    eq_series = pd.Series([e["equity"] for e in equity_curve]); returns = eq_series.pct_change().dropna(); sharpe = (returns.mean() / returns.std() * math.sqrt(252)) if returns.std() > 0 else 0; downside = returns[returns < 0]; sortino = (returns.mean() / downside.std() * math.sqrt(252)) if len(downside) > 0 and downside.std() > 0 else 0; rolling_max = eq_series.cummax(); drawdowns = (eq_series - rolling_max) / rolling_max * 100; max_dd = float(drawdowns.min()) if len(drawdowns) else 0; days = (pd.Timestamp(end_date) - pd.Timestamp(start_date)).days; years = days / 365.25 if days > 0 else 1; cagr = ((capital / initial_capital) ** (1 / years) - 1) * 100 if years > 0 else 0
    return {"ticker": ticker, "asset_type": asset_type, "strategy": strategy_name, "start_date": start_date, "end_date": end_date, "interval": interval, "bars": len(df), "capital_start": initial_capital, "capital_end": round(capital, 2), "total_return_pct": round((capital / initial_capital - 1) * 100, 2), "cagr_pct": round(cagr, 2), "total_trades": total, "wins": len(wins), "losses": len(losses), "win_rate": round(win_rate, 2), "profit_factor": round(profit_factor, 2), "sharpe": round(sharpe, 2), "sortino": round(sortino, 2), "max_drawdown": round(max_dd, 2), "avg_win": round(avg_win, 2), "avg_loss": round(avg_loss, 2), "expectancy": round(expectancy, 2), "gross_profit": round(gross_profit, 2), "gross_loss": round(gross_loss, 2), "equity_curve": equity_curve, "drawdown_curve": drawdown_curve, "trades": trades, "params": {"min_confidence": min_confidence, "risk_per_trade": risk_per_trade, "sl_atr_mult": sl_atr_mult, "tp_atr_mult": tp_atr_mult, "fee_bps": fee_bps, "slippage_bps": slip_bps if False else slippage_bps, "spread_bps": spread_bps, "max_hold_bars": max_hold_bars}, "status": "completed"}


async def run_compare(ticker, asset_type, start_date, end_date, interval, initial_capital, strategies: list, **kwargs):
    results = await asyncio.gather(*[run_backtest(ticker, asset_type, start_date, end_date, interval, initial_capital, strategy=s, **kwargs) for s in strategies])
    out = {"ticker": ticker, "strategies": {}}
    for r in results:
        s = r.get("strategy", "unknown")
        out["strategies"][s] = {"error": r["error"]} if "error" in r else {"total_return_pct": r["total_return_pct"], "sharpe": r["sharpe"], "max_drawdown": r["max_drawdown"], "win_rate": r["win_rate"], "profit_factor": r["profit_factor"], "total_trades": r["total_trades"], "expectancy": r["expectancy"], "equity_curve": r["equity_curve"], "drawdown_curve": r["drawdown_curve"]}
    return out
