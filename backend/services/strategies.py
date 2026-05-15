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


def _adx_like(highs, lows, closes, period=14):
    if len(closes) < period + 2:
        return 20
    plus_dm, minus_dm, tr = [], [], []
    for i in range(-period, 0):
        up_move = highs[i] - highs[i - 1]
        down_move = lows[i - 1] - lows[i]
        plus_dm.append(up_move if up_move > down_move and up_move > 0 else 0)
        minus_dm.append(down_move if down_move > up_move and down_move > 0 else 0)
        tr.append(max(highs[i] - lows[i], abs(highs[i] - closes[i - 1]), abs(lows[i] - closes[i - 1])))
    tr_sum = max(float(np.sum(tr)), 1e-9)
    plus_di = 100 * float(np.sum(plus_dm)) / tr_sum
    minus_di = 100 * float(np.sum(minus_dm)) / tr_sum
    dx = 100 * abs(plus_di - minus_di) / max(plus_di + minus_di, 1e-9)
    return float(dx)


def _stoch_rsi(closes, period=14):
    if len(closes) < period * 2:
        return 50
    rsis = []
    for i in range(period, 0, -1):
        rsis.append(_rsi(closes[:-i] if i > 1 else closes, period))
    low, high = min(rsis), max(rsis)
    if high - low < 1e-9:
        return 50
    return 100 * (rsis[-1] - low) / (high - low)


def _vwap(highs, lows, closes, volumes, period=20):
    if len(closes) == 0:
        return 0
    p = min(period, len(closes))
    typical = (highs[-p:] + lows[-p:] + closes[-p:]) / 3
    vols = volumes[-p:]
    return float(np.sum(typical * vols) / max(np.sum(vols), 1e-9))


def _calibrated(signal, confidence, atr_pct, strategy, window):
    if signal == "HOLD" or len(window) < 60:
        return {"signal": signal, "confidence": int(confidence), "atr_pct": atr_pct, "strategy": strategy}

    closes = window["close"].values
    highs = window["high"].values
    lows = window["low"].values
    opens = window["open"].values
    volumes = window["volume"].values
    close = float(closes[-1])
    open_ = float(opens[-1])
    direction = 1 if "BUY" in signal else -1

    ema20 = _ema(closes[-40:], 20)
    ema50 = _ema(closes[-80:], 50) if len(closes) >= 80 else _ema(closes[-60:], 50)
    ema50_prev = _ema(closes[-100:-20], 50) if len(closes) >= 100 else ema50
    rsi = _rsi(closes)
    stoch = _stoch_rsi(closes)
    adx = _adx_like(highs, lows, closes)
    vwap = _vwap(highs, lows, closes, volumes)
    vol_avg = float(np.mean(volumes[-20:])) if len(volumes) >= 20 else float(volumes[-1])
    vol_ratio = float(volumes[-1]) / max(vol_avg, 1e-9)
    body_ratio = abs(close - open_) / max(float(highs[-1] - lows[-1]), 1e-9)

    boost = 0
    trend_aligned = (direction == 1 and close > ema20 > ema50 and ema50 >= ema50_prev) or (direction == -1 and close < ema20 < ema50 and ema50 <= ema50_prev)
    if trend_aligned:
        boost += 7
    if adx >= 25:
        boost += 6 if trend_aligned else 2
    elif adx < 15 and strategy in ("trend_follow", "breakout", "volatility_breakout"):
        boost -= 7

    vwap_aligned = (direction == 1 and close > vwap) or (direction == -1 and close < vwap)
    if vwap_aligned:
        boost += 4
    else:
        boost -= 3

    momentum_ok = (direction == 1 and 42 <= rsi <= 68 and stoch < 90) or (direction == -1 and 32 <= rsi <= 58 and stoch > 10)
    if momentum_ok:
        boost += 5
    elif (direction == 1 and rsi > 78) or (direction == -1 and rsi < 22):
        boost -= 6

    candle_confirms = (direction == 1 and close > open_) or (direction == -1 and close < open_)
    if candle_confirms and body_ratio >= 0.45:
        boost += 5
    elif body_ratio < 0.2:
        boost -= 4

    if vol_ratio >= 1.25:
        boost += 5
    elif vol_ratio < 0.75:
        boost -= 6

    if atr_pct < 0.15:
        boost -= 8
    elif 0.25 <= atr_pct <= 4.0:
        boost += 3
    elif atr_pct > 8.0:
        boost -= 10

    return {"signal": signal, "confidence": int(max(0, min(95, confidence + boost))), "atr_pct": atr_pct, "strategy": strategy}


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
        score = 3
    elif ema12 > ema26:
        score = 2
    elif ema12 < ema26 < ema50 and close < ema12:
        score = -3
    elif ema12 < ema26:
        score = -2

    if score >= 2:
        return _calibrated("BUY" if score < 3 else "STRONG_BUY", 55 + score * 5, atr_pct, "trend_follow", window)
    if score <= -2:
        return _calibrated("SELL" if score > -3 else "STRONG_SELL", 55 + abs(score) * 5, atr_pct, "trend_follow", window)
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
        return _calibrated("STRONG_BUY", 75, atr_pct, "mean_revert", window)
    if rsi < 35:
        return _calibrated("BUY", 60, atr_pct, "mean_revert", window)
    if rsi > 75 and close > bb_upper:
        return _calibrated("STRONG_SELL", 75, atr_pct, "mean_revert", window)
    if rsi > 65:
        return _calibrated("SELL", 60, atr_pct, "mean_revert", window)
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
        return _calibrated("STRONG_BUY", 72, atr_pct, "breakout", window)
    if close > donch_high:
        return _calibrated("BUY", 58, atr_pct, "breakout", window)
    if close < donch_low and vol_now > vol_avg * 1.2:
        return _calibrated("STRONG_SELL", 72, atr_pct, "breakout", window)
    if close < donch_low:
        return _calibrated("SELL", 58, atr_pct, "breakout", window)
    return {"signal": "HOLD", "confidence": 40, "atr_pct": atr_pct, "strategy": "breakout"}


def ensemble(window):
    """Vote-blend of all three strategies, returns the strongest signal."""
    results = [trend_follow(window), mean_revert(window), breakout(window)]
    buy_score = sum(r["confidence"] for r in results if "BUY" in r["signal"])
    sell_score = sum(r["confidence"] for r in results if "SELL" in r["signal"])
    atr_pct = max(r["atr_pct"] for r in results)
    if buy_score > sell_score and buy_score > 100:
        return _calibrated("STRONG_BUY" if buy_score > 150 else "BUY", min(85, buy_score // 2 + 30), atr_pct, "ensemble", window)
    if sell_score > buy_score and sell_score > 100:
        return _calibrated("STRONG_SELL" if sell_score > 150 else "SELL", min(85, sell_score // 2 + 30), atr_pct, "ensemble", window)
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
        return _calibrated("STRONG_BUY", 72, atr_pct, "momentum_pullback", window)
    if downtrend and close >= ema20 * 0.99 and 50 < rsi < 65:
        return _calibrated("STRONG_SELL", 72, atr_pct, "momentum_pullback", window)
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
        return _calibrated("STRONG_BUY", 70, atr_pct, "volatility_breakout", window)
    if expansion and close < open_ and vol_confirm:
        return _calibrated("STRONG_SELL", 70, atr_pct, "volatility_breakout", window)
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

    if gap_pct > 1.5 and intraday_pct < -0.2:
        return _calibrated("SELL", 62, atr_pct, "gap_fade", window)
    if gap_pct < -1.5 and intraday_pct > 0.2:
        return _calibrated("BUY", 62, atr_pct, "gap_fade", window)
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