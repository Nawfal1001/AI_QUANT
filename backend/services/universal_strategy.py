"""
Universal parameter-driven strategy.

Designed to be optimised by Optuna across symbols and timeframes. Mixes four
families of indicators — trend (EMA fast/slow), momentum (RSI), volatility
(ATR + Bollinger), and breakout (Donchian) — into a weighted score, then maps
the score to BUY/SELL/HOLD using configurable thresholds.

Public API:
    universal(window, params=None)  -> {signal, confidence, atr_pct, strategy}
    make_universal_fn(params)       -> callable(window) -> result dict
    UNIVERSAL_PARAM_SPACE           -> dict describing optimisable ranges

The window is a pandas DataFrame containing at least `open/high/low/close/volume`
columns. All parameters have sane defaults so the strategy works with zero
configuration (matches the behaviour of the built-in strategies).
"""
from __future__ import annotations
import numpy as np
from services.strategies import _ema, _rsi, _atr, _adx_like, _calibrated

DEFAULT_PARAMS = {
    "ema_fast": 12,
    "ema_slow": 26,
    "ema_trend": 50,
    "rsi_period": 14,
    "rsi_buy": 55,
    "rsi_sell": 45,
    "bb_period": 20,
    "bb_std": 2.0,
    "donchian": 20,
    "adx_min": 18.0,
    "atr_period": 14,
    "vol_ratio_min": 0.8,
    "weight_trend": 1.0,
    "weight_momentum": 0.8,
    "weight_breakout": 0.9,
    "weight_meanrev": 0.6,
    "buy_threshold": 1.2,
    "sell_threshold": -1.2,
    "min_bars": 60,
}

UNIVERSAL_PARAM_SPACE = {
    "ema_fast": ("int", 5, 30),
    "ema_slow": ("int", 20, 80),
    "ema_trend": ("int", 30, 200),
    "rsi_period": ("int", 7, 28),
    "rsi_buy": ("int", 45, 65),
    "rsi_sell": ("int", 30, 55),
    "bb_period": ("int", 10, 40),
    "bb_std": ("float", 1.5, 3.0),
    "donchian": ("int", 10, 60),
    "adx_min": ("float", 10.0, 35.0),
    "weight_trend": ("float", 0.0, 2.0),
    "weight_momentum": ("float", 0.0, 2.0),
    "weight_breakout": ("float", 0.0, 2.0),
    "weight_meanrev": ("float", 0.0, 2.0),
    "buy_threshold": ("float", 0.5, 2.5),
    "sell_threshold": ("float", -2.5, -0.5),
}


def _merge(params):
    p = dict(DEFAULT_PARAMS)
    if params:
        for k, v in params.items():
            if k in p and v is not None:
                p[k] = v
    if p["ema_fast"] >= p["ema_slow"]:
        p["ema_fast"] = max(2, int(p["ema_slow"] // 2))
    return p


def universal(window, params=None):
    p = _merge(params)
    min_bars = max(int(p["min_bars"]), int(p["ema_trend"]) + 5)
    if window is None or len(window) < min_bars:
        return {"signal": "HOLD", "confidence": 0, "atr_pct": 0, "strategy": "universal"}

    closes = window["close"].values.astype(float)
    highs = window["high"].values.astype(float)
    lows = window["low"].values.astype(float)
    volumes = window["volume"].values.astype(float) if "volume" in window.columns else np.zeros(len(closes))
    close = float(closes[-1])

    ema_f = _ema(closes[-int(p["ema_slow"]) * 2:], int(p["ema_fast"]))
    ema_s = _ema(closes[-int(p["ema_slow"]) * 2:], int(p["ema_slow"]))
    ema_t = _ema(closes[-int(p["ema_trend"]) * 2:], int(p["ema_trend"]))
    rsi = _rsi(closes, int(p["rsi_period"]))
    atr = _atr(highs, lows, closes, int(p["atr_period"]))
    atr_pct = atr / close * 100 if close else 0.0
    adx = _adx_like(highs, lows, closes, int(p["atr_period"]))

    bb_n = int(p["bb_period"])
    bb_mean = float(np.mean(closes[-bb_n:]))
    bb_std = float(np.std(closes[-bb_n:]))
    bb_upper = bb_mean + p["bb_std"] * bb_std
    bb_lower = bb_mean - p["bb_std"] * bb_std

    don_n = int(p["donchian"])
    don_high = float(np.max(highs[-(don_n + 1):-1])) if len(highs) > don_n else float(np.max(highs))
    don_low = float(np.min(lows[-(don_n + 1):-1])) if len(lows) > don_n else float(np.min(lows))

    vol_avg = float(np.mean(volumes[-20:])) if len(volumes) >= 20 else float(np.mean(volumes) or 1.0)
    vol_now = float(volumes[-1]) if len(volumes) else 0.0
    vol_ratio = vol_now / max(vol_avg, 1e-9)

    # Trend component
    trend = 0.0
    if ema_f > ema_s > ema_t and close > ema_f:
        trend = 1.0
    elif ema_f > ema_s:
        trend = 0.5
    elif ema_f < ema_s < ema_t and close < ema_f:
        trend = -1.0
    elif ema_f < ema_s:
        trend = -0.5
    if adx < p["adx_min"]:
        trend *= 0.4

    # Momentum component
    momentum = 0.0
    if rsi >= p["rsi_buy"]:
        momentum = min(1.0, (rsi - p["rsi_buy"]) / max(70 - p["rsi_buy"], 1.0))
    elif rsi <= p["rsi_sell"]:
        momentum = -min(1.0, (p["rsi_sell"] - rsi) / max(p["rsi_sell"] - 30, 1.0))

    # Breakout component (Donchian + volume confirm)
    breakout = 0.0
    vol_ok = vol_ratio >= p["vol_ratio_min"]
    if close > don_high:
        breakout = 1.0 if vol_ok else 0.5
    elif close < don_low:
        breakout = -1.0 if vol_ok else -0.5

    # Mean-reversion component (Bollinger fade — opposite sign of price extreme)
    meanrev = 0.0
    if close <= bb_lower and rsi < 35:
        meanrev = 1.0
    elif close >= bb_upper and rsi > 65:
        meanrev = -1.0

    score = (
        trend * p["weight_trend"]
        + momentum * p["weight_momentum"]
        + breakout * p["weight_breakout"]
        + meanrev * p["weight_meanrev"]
    )

    if score >= p["buy_threshold"]:
        signal = "STRONG_BUY" if score >= p["buy_threshold"] * 1.5 else "BUY"
        confidence = int(55 + min(35, abs(score) * 12))
        return _calibrated(signal, confidence, atr_pct, "universal", window)
    if score <= p["sell_threshold"]:
        signal = "STRONG_SELL" if score <= p["sell_threshold"] * 1.5 else "SELL"
        confidence = int(55 + min(35, abs(score) * 12))
        return _calibrated(signal, confidence, atr_pct, "universal", window)

    return {"signal": "HOLD", "confidence": 40, "atr_pct": atr_pct, "strategy": "universal"}


def make_universal_fn(params):
    p = _merge(params)
    def _fn(window):
        return universal(window, p)
    _fn.params = p
    return _fn


def universal_meta():
    return {
        "id": "universal",
        "name": "Universal Multi-Factor",
        "desc": "Parameter-driven mix of trend, momentum, breakout and mean-reversion. Optimised by Optuna.",
        "builtin": True,
        "param_space": UNIVERSAL_PARAM_SPACE,
        "defaults": DEFAULT_PARAMS,
    }
