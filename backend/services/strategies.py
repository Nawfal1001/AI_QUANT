"""
Pluggable strategy functions for backtest engine.
Each strategy takes a closed-bar window and returns {signal, confidence, atr_pct}.
"""
import numpy as np


def _ema(arr, period):
    if len(arr) == 0:
        return 0
    k = 2 / (period + 1)
    e = arr[0]
    for x in arr[1:]:
        e = x * k + e * (1 - k)
    return e


def _rsi(closes, period=14):
    if len(closes) < period + 1:
        return 50
    delta = np.diff(closes)
    gains = np.where(delta > 0, delta, 0)
    losses = np.where(delta < 0, -delta, 0)
    avg_gain = np.mean(gains[-period:])
    avg_loss = np.mean(losses[-period:])
    rs = avg_gain / max(avg_loss, 1e-9)
    return 100 - (100 / (1 + rs))


def _atr(highs, lows, closes, period=14):
    if len(highs) < period + 1:
        return 0
    trs = []
    for i in range(1, min(period + 1, len(highs))):
        h, l, pc = highs[-i], lows[-i], closes[-i - 1]
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    return float(np.mean(trs)) if trs else 0


def trend_follow(window):
    """EMA + MACD + ADX style trend-following."""
    if len(window) < 50:
        return {"signal": "HOLD", "confidence": 0, "atr_pct": 0, "strategy": "trend_follow"}
    closes = window["close"].values
    highs = window["high"].values
    lows = window["low"].values
    close = closes[-1]
    ema12 = _ema(closes[-30:], 12)
    ema26 = _ema(closes[-50:], 26)
    ema50 = _ema(closes[-50:], 50) if len(closes) >= 50 else ema26
    atr = _atr(highs, lows, closes)
    atr_pct = atr / close * 100 if close else 0

    score = 0
    if ema12 > ema26 > ema50 and close > ema12:
        score = 3  # strong uptrend
    elif ema12 > ema26:
        score = 2
    elif ema12 < ema26 < ema50 and close < ema12:
        score = -3
    elif ema12 < ema26:
        score = -2

    if score >= 2:
        return {"signal": "BUY" if score < 3 else "STRONG_BUY", "confidence": 55 + score * 5, "atr_pct": atr_pct, "strategy": "trend_follow"}
    if score <= -2:
        return {"signal": "SELL" if score > -3 else "STRONG_SELL", "confidence": 55 + abs(score) * 5, "atr_pct": atr_pct, "strategy": "trend_follow"}
    return {"signal": "HOLD", "confidence": 40, "atr_pct": atr_pct, "strategy": "trend_follow"}


def mean_revert(window):
    """RSI + Bollinger mean reversion."""
    if len(window) < 30:
        return {"signal": "HOLD", "confidence": 0, "atr_pct": 0, "strategy": "mean_revert"}
    closes = window["close"].values
    highs = window["high"].values
    lows = window["low"].values
    close = closes[-1]
    rsi = _rsi(closes)
    bb_mean = np.mean(closes[-20:])
    bb_std = np.std(closes[-20:])
    bb_upper = bb_mean + 2 * bb_std
    bb_lower = bb_mean - 2 * bb_std
    atr = _atr(highs, lows, closes)
    atr_pct = atr / close * 100 if close else 0

    if rsi < 25 and close < bb_lower:
        return {"signal": "STRONG_BUY", "confidence": 75, "atr_pct": atr_pct, "strategy": "mean_revert"}
    if rsi < 35:
        return {"signal": "BUY", "confidence": 60, "atr_pct": atr_pct, "strategy": "mean_revert"}
    if rsi > 75 and close > bb_upper:
        return {"signal": "STRONG_SELL", "confidence": 75, "atr_pct": atr_pct, "strategy": "mean_revert"}
    if rsi > 65:
        return {"signal": "SELL", "confidence": 60, "atr_pct": atr_pct, "strategy": "mean_revert"}
    return {"signal": "HOLD", "confidence": 40, "atr_pct": atr_pct, "strategy": "mean_revert"}


def breakout(window):
    """Donchian channel breakout (20-bar high/low)."""
    if len(window) < 25:
        return {"signal": "HOLD", "confidence": 0, "atr_pct": 0, "strategy": "breakout"}
    closes = window["close"].values
    highs = window["high"].values
    lows = window["low"].values
    volumes = window["volume"].values
    close = closes[-1]
    donch_high = max(highs[-21:-1])
    donch_low = min(lows[-21:-1])
    vol_avg = np.mean(volumes[-20:]) if len(volumes) >= 20 else volumes[-1]
    vol_now = volumes[-1]
    atr = _atr(highs, lows, closes)
    atr_pct = atr / close * 100 if close else 0

    if close > donch_high and vol_now > vol_avg * 1.2:
        return {"signal": "STRONG_BUY", "confidence": 72, "atr_pct": atr_pct, "strategy": "breakout"}
    if close > donch_high:
        return {"signal": "BUY", "confidence": 58, "atr_pct": atr_pct, "strategy": "breakout"}
    if close < donch_low and vol_now > vol_avg * 1.2:
        return {"signal": "STRONG_SELL", "confidence": 72, "atr_pct": atr_pct, "strategy": "breakout"}
    if close < donch_low:
        return {"signal": "SELL", "confidence": 58, "atr_pct": atr_pct, "strategy": "breakout"}
    return {"signal": "HOLD", "confidence": 40, "atr_pct": atr_pct, "strategy": "breakout"}


def ensemble(window):
    """Vote-blend of all three strategies, returns the strongest signal."""
    results = [trend_follow(window), mean_revert(window), breakout(window)]
    buy_score = sum(r["confidence"] for r in results if "BUY" in r["signal"])
    sell_score = sum(r["confidence"] for r in results if "SELL" in r["signal"])
    atr_pct = max(r["atr_pct"] for r in results)
    if buy_score > sell_score and buy_score > 100:
        return {"signal": "STRONG_BUY" if buy_score > 150 else "BUY", "confidence": min(85, buy_score // 2 + 30), "atr_pct": atr_pct, "strategy": "ensemble"}
    if sell_score > buy_score and sell_score > 100:
        return {"signal": "STRONG_SELL" if sell_score > 150 else "SELL", "confidence": min(85, sell_score // 2 + 30), "atr_pct": atr_pct, "strategy": "ensemble"}
    return {"signal": "HOLD", "confidence": 40, "atr_pct": atr_pct, "strategy": "ensemble"}


def momentum_pullback(window):
    """Buys pullbacks to EMA20 inside an established uptrend with cooled RSI."""
    if len(window) < 60:
        return {"signal": "HOLD", "confidence": 0, "atr_pct": 0, "strategy": "momentum_pullback"}
    closes = window["close"].values
    highs = window["high"].values
    lows = window["low"].values
    close = closes[-1]
    ema20 = _ema(closes[-30:], 20)
    ema50 = _ema(closes[-60:], 50)
    ema50_prior = _ema(closes[-90:-30], 50) if len(closes) >= 90 else ema50
    rsi = _rsi(closes)
    atr = _atr(highs, lows, closes)
    atr_pct = atr / close * 100 if close else 0

    uptrend = close > ema50 and ema50 > ema50_prior
    downtrend = close < ema50 and ema50 < ema50_prior

    if uptrend and close <= ema20 * 1.01 and 35 < rsi < 50:
        return {"signal": "STRONG_BUY", "confidence": 72, "atr_pct": atr_pct, "strategy": "momentum_pullback"}
    if downtrend and close >= ema20 * 0.99 and 50 < rsi < 65:
        return {"signal": "STRONG_SELL", "confidence": 72, "atr_pct": atr_pct, "strategy": "momentum_pullback"}
    return {"signal": "HOLD", "confidence": 40, "atr_pct": atr_pct, "strategy": "momentum_pullback"}


def volatility_breakout(window):
    """ATR-expansion breakout — fires when range expands sharply with directional close."""
    if len(window) < 30:
        return {"signal": "HOLD", "confidence": 0, "atr_pct": 0, "strategy": "volatility_breakout"}
    closes = window["close"].values
    highs = window["high"].values
    lows = window["low"].values
    opens = window["open"].values
    volumes = window["volume"].values
    close = closes[-1]
    open_ = opens[-1]

    atr_now = _atr(highs, lows, closes, period=5)
    atr_long = _atr(highs, lows, closes, period=20)
    atr_pct = atr_now / close * 100 if close else 0

    bar_range = highs[-1] - lows[-1]
    avg_range = np.mean(highs[-20:] - lows[-20:]) if len(highs) >= 20 else bar_range
    vol_now = volumes[-1]
    vol_avg = np.mean(volumes[-20:]) if len(volumes) >= 20 else vol_now

    expansion = atr_now > atr_long * 1.4 and bar_range > avg_range * 1.5
    vol_confirm = vol_now > vol_avg * 1.3

    if expansion and close > open_ and vol_confirm:
        return {"signal": "STRONG_BUY", "confidence": 70, "atr_pct": atr_pct, "strategy": "volatility_breakout"}
    if expansion and close < open_ and vol_confirm:
        return {"signal": "STRONG_SELL", "confidence": 70, "atr_pct": atr_pct, "strategy": "volatility_breakout"}
    return {"signal": "HOLD", "confidence": 40, "atr_pct": atr_pct, "strategy": "volatility_breakout"}


def gap_fade(window):
    """Fades opening gaps that don't follow through — common in liquid stocks."""
    if len(window) < 30:
        return {"signal": "HOLD", "confidence": 0, "atr_pct": 0, "strategy": "gap_fade"}
    closes = window["close"].values
    highs = window["high"].values
    lows = window["low"].values
    opens = window["open"].values
    close = closes[-1]
    open_ = opens[-1]
    prev_close = closes[-2] if len(closes) >= 2 else close

    atr = _atr(highs, lows, closes)
    atr_pct = atr / close * 100 if close else 0
    gap_pct = (open_ - prev_close) / prev_close * 100 if prev_close else 0
    intraday_pct = (close - open_) / open_ * 100 if open_ else 0

    # Big gap up that's losing strength → fade
    if gap_pct > 1.5 and intraday_pct < -0.2:
        return {"signal": "SELL", "confidence": 62, "atr_pct": atr_pct, "strategy": "gap_fade"}
    # Big gap down rebounding → buy the dip
    if gap_pct < -1.5 and intraday_pct > 0.2:
        return {"signal": "BUY", "confidence": 62, "atr_pct": atr_pct, "strategy": "gap_fade"}
    return {"signal": "HOLD", "confidence": 40, "atr_pct": atr_pct, "strategy": "gap_fade"}


STRATEGIES = {
    "trend_follow": trend_follow,
    "mean_revert": mean_revert,
    "breakout": breakout,
    "ensemble": ensemble,
    "momentum_pullback": momentum_pullback,
    "volatility_breakout": volatility_breakout,
    "gap_fade": gap_fade,
}


def list_strategies():
    return [
        {"id": "trend_follow", "name": "Trend Following", "desc": "EMA + MACD cascade — buys breakouts above trend, sells under", "builtin": True},
        {"id": "mean_revert", "name": "Mean Reversion", "desc": "RSI + Bollinger — fades extremes, best in ranging markets", "builtin": True},
        {"id": "breakout", "name": "Donchian Breakout", "desc": "20-bar high/low breaks with volume confirm", "builtin": True},
        {"id": "ensemble", "name": "Ensemble Vote", "desc": "Weighted blend of trend + revert + breakout", "builtin": True},
        {"id": "momentum_pullback", "name": "Momentum Pullback", "desc": "Buys pullbacks to EMA20 inside an established uptrend", "builtin": True},
        {"id": "volatility_breakout", "name": "Volatility Breakout", "desc": "ATR-expansion + volume + directional close", "builtin": True},
        {"id": "gap_fade", "name": "Gap Fade", "desc": "Fades opening gaps that lose follow-through", "builtin": True},
    ]
