from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Dict, List

import pandas as pd


@dataclass
class Evidence:
    name: str
    buy: float
    sell: float
    hold: float
    reason: str


class RegimeKalmanDempsterStrategy:
    """
    Advanced probabilistic strategy using:
    - HMM-inspired regime detection: trend/range/high-volatility/quiet states
    - Kalman filter smoothing: cleaner trend estimate and slope
    - Dempster-Shafer evidence fusion: combines uncertain/conflicting evidence

    This version avoids heavy external dependencies so it can be backtested and
    optimized inside the current app environment.
    """

    name = "Regime Kalman Dempster Strategy"
    slug = "regime_kalman_dempster"
    description = "HMM-style regime detection + Kalman trend smoothing + Dempster-Shafer evidence fusion."

    defaults: Dict[str, Any] = {
        "returns_period": 20,
        "vol_period": 20,
        "trend_period": 50,
        "atr_period": 14,
        "rsi_period": 14,
        "bb_period": 20,
        "bb_std": 2.0,
        "volume_period": 20,
        "kalman_q": 0.0001,
        "kalman_r": 0.01,
        "trend_slope_threshold": 0.0015,
        "high_vol_quantile": 0.70,
        "low_vol_quantile": 0.30,
        "buy_threshold": 0.62,
        "sell_threshold": 0.62,
        "max_conflict": 0.42,
        "min_confidence": 0.58,
        "risk_reward": 1.8,
        "atr_stop_mult": 1.7,
    }

    def __init__(self, **params: Any):
        self.params = {**self.defaults, **params}

    @staticmethod
    def _f(v: Any, default: float = 0.0) -> float:
        try:
            return float(v)
        except Exception:
            return default

    @staticmethod
    def _ema(s: pd.Series, n: int) -> pd.Series:
        return s.ewm(span=int(n), adjust=False).mean()

    @staticmethod
    def _rsi(close: pd.Series, n: int = 14) -> pd.Series:
        delta = close.diff()
        gain = delta.clip(lower=0).rolling(n).mean()
        loss = (-delta.clip(upper=0)).rolling(n).mean()
        rs = gain / loss.replace(0, float("nan"))
        return 100 - (100 / (1 + rs))

    @staticmethod
    def _atr(df: pd.DataFrame, n: int = 14) -> pd.Series:
        high, low, close = df["high"], df["low"], df["close"]
        tr = pd.concat([(high - low), (high - close.shift()).abs(), (low - close.shift()).abs()], axis=1).max(axis=1)
        return tr.rolling(n).mean()

    @staticmethod
    def _kalman(close: pd.Series, q: float, r: float) -> pd.Series:
        values = close.astype(float).values
        if len(values) == 0:
            return close
        x = values[0]
        p = 1.0
        out = []
        for z in values:
            p = p + q
            k = p / (p + r)
            x = x + k * (z - x)
            p = (1 - k) * p
            out.append(x)
        return pd.Series(out, index=close.index)

    @staticmethod
    def _combine_two(a: Evidence, b: Evidence) -> Evidence:
        keys = ("buy", "sell", "hold")
        ma = {"buy": a.buy, "sell": a.sell, "hold": a.hold}
        mb = {"buy": b.buy, "sell": b.sell, "hold": b.hold}
        conflict = ma["buy"] * mb["sell"] + ma["sell"] * mb["buy"]
        denom = max(1e-9, 1 - conflict)
        combined = {}
        for k in keys:
            combined[k] = (ma[k] * mb[k] + ma[k] * mb["hold"] + ma["hold"] * mb[k]) / denom
        total = sum(combined.values()) or 1
        return Evidence(
            name=f"{a.name}+{b.name}",
            buy=combined["buy"] / total,
            sell=combined["sell"] / total,
            hold=combined["hold"] / total,
            reason=f"conflict={round(conflict, 4)}",
        )

    @classmethod
    def _combine_all(cls, evidences: List[Evidence]) -> Evidence:
        if not evidences:
            return Evidence("none", 0.0, 0.0, 1.0, "no evidence")
        cur = evidences[0]
        for e in evidences[1:]:
            cur = cls._combine_two(cur, e)
        return cur

    def add_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        p = self.params
        out = df.copy()
        out.columns = [c.lower() for c in out.columns]
        out["returns"] = out["close"].pct_change()
        out["volatility"] = out["returns"].rolling(p["vol_period"]).std()
        out["vol_hi"] = out["volatility"].rolling(120).quantile(p["high_vol_quantile"])
        out["vol_lo"] = out["volatility"].rolling(120).quantile(p["low_vol_quantile"])
        out["ema_trend"] = self._ema(out["close"], p["trend_period"])
        out["kalman"] = self._kalman(out["close"], p["kalman_q"], p["kalman_r"])
        out["kalman_slope"] = out["kalman"].pct_change(5)
        out["rsi"] = self._rsi(out["close"], p["rsi_period"])
        mid = out["close"].rolling(p["bb_period"]).mean()
        std = out["close"].rolling(p["bb_period"]).std()
        out["bb_upper"] = mid + p["bb_std"] * std
        out["bb_lower"] = mid - p["bb_std"] * std
        out["bb_pos"] = (out["close"] - out["bb_lower"]) / (out["bb_upper"] - out["bb_lower"]).replace(0, float("nan"))
        out["atr"] = self._atr(out, p["atr_period"])
        out["volume_ma"] = out.get("volume", pd.Series(index=out.index, data=0)).rolling(p["volume_period"]).mean()
        out["volume_ratio"] = out.get("volume", pd.Series(index=out.index, data=0)) / out["volume_ma"].replace(0, float("nan"))
        out["range_high"] = out["high"].rolling(20).max().shift(1)
        out["range_low"] = out["low"].rolling(20).min().shift(1)
        return out

    def _regime(self, row: pd.Series) -> str:
        p = self.params
        slope = self._f(row.get("kalman_slope"))
        vol = self._f(row.get("volatility"))
        hi = self._f(row.get("vol_hi"), vol * 2)
        lo = self._f(row.get("vol_lo"), vol / 2)
        if vol >= hi:
            return "HIGH_VOLATILITY"
        if vol <= lo:
            return "QUIET"
        if slope > p["trend_slope_threshold"] and row["close"] > row["ema_trend"]:
            return "TREND_UP"
        if slope < -p["trend_slope_threshold"] and row["close"] < row["ema_trend"]:
            return "TREND_DOWN"
        return "RANGE"

    def _evidence(self, row: pd.Series, regime: str) -> List[Evidence]:
        ev: List[Evidence] = []
        slope = self._f(row.get("kalman_slope"))
        if slope > 0:
            ev.append(Evidence("kalman_trend", 0.60 + min(0.25, abs(slope) * 50), 0.08, 0.32, "Kalman slope bullish"))
        elif slope < 0:
            ev.append(Evidence("kalman_trend", 0.08, 0.60 + min(0.25, abs(slope) * 50), 0.32, "Kalman slope bearish"))
        if regime == "TREND_UP":
            ev.append(Evidence("hmm_regime", 0.70, 0.05, 0.25, "HMM-style regime trend up"))
        elif regime == "TREND_DOWN":
            ev.append(Evidence("hmm_regime", 0.05, 0.70, 0.25, "HMM-style regime trend down"))
        elif regime == "HIGH_VOLATILITY":
            ev.append(Evidence("hmm_regime", 0.20, 0.20, 0.60, "High volatility: caution"))
        elif regime == "QUIET":
            ev.append(Evidence("hmm_regime", 0.25, 0.25, 0.50, "Quiet market: wait for confirmation"))
        else:
            ev.append(Evidence("hmm_regime", 0.30, 0.30, 0.40, "Range regime"))
        rsi = self._f(row.get("rsi"))
        bbp = self._f(row.get("bb_pos"), 0.5)
        if regime == "RANGE" and rsi < 35 and bbp < 0.2:
            ev.append(Evidence("range_reversion", 0.68, 0.05, 0.27, "Oversold range reversion"))
        elif regime == "RANGE" and rsi > 65 and bbp > 0.8:
            ev.append(Evidence("range_reversion", 0.05, 0.68, 0.27, "Overbought range reversion"))
        elif rsi > 55 and regime in ("TREND_UP", "QUIET"):
            ev.append(Evidence("momentum", 0.58, 0.12, 0.30, "Bullish RSI momentum"))
        elif rsi < 45 and regime in ("TREND_DOWN", "QUIET"):
            ev.append(Evidence("momentum", 0.12, 0.58, 0.30, "Bearish RSI momentum"))
        vol_ok = self._f(row.get("volume_ratio")) > 1.2
        if row["close"] > row.get("range_high", float("inf")) and vol_ok:
            ev.append(Evidence("breakout", 0.72, 0.04, 0.24, "Bullish breakout with volume"))
        elif row["close"] < row.get("range_low", -float("inf")) and vol_ok:
            ev.append(Evidence("breakout", 0.04, 0.72, 0.24, "Bearish breakout with volume"))
        return ev

    def signal_row(self, row: pd.Series) -> Dict[str, Any]:
        p = self.params
        regime = self._regime(row)
        evidences = self._evidence(row, regime)
        fused = self._combine_all(evidences)
        conflict = 1 - max(fused.buy, fused.sell, fused.hold)
        signal = "HOLD"
        confidence = max(fused.buy, fused.sell, fused.hold)
        if fused.buy >= p["buy_threshold"] and confidence >= p["min_confidence"] and conflict <= p["max_conflict"]:
            signal = "BUY"
        elif fused.sell >= p["sell_threshold"] and confidence >= p["min_confidence"] and conflict <= p["max_conflict"]:
            signal = "SELL"
        price = self._f(row.get("close"))
        atr = self._f(row.get("atr"), price * 0.02)
        if signal == "BUY":
            sl = price - p["atr_stop_mult"] * atr
            tp = price + p["atr_stop_mult"] * p["risk_reward"] * atr
        elif signal == "SELL":
            sl = price + p["atr_stop_mult"] * atr
            tp = price - p["atr_stop_mult"] * p["risk_reward"] * atr
        else:
            sl = tp = None
        return {
            "signal": signal,
            "regime": regime,
            "confidence": round(confidence * 100, 2),
            "belief_buy": round(fused.buy, 4),
            "belief_sell": round(fused.sell, 4),
            "belief_hold": round(fused.hold, 4),
            "conflict": round(conflict, 4),
            "price": round(price, 6),
            "sl": round(sl, 6) if sl is not None else None,
            "tp": round(tp, 6) if tp is not None else None,
            "evidence": [e.__dict__ for e in evidences],
        }

    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        out = self.add_indicators(df)
        rows = []
        for _, row in out.iterrows():
            if row.isna().any():
                rows.append({"signal": "HOLD", "confidence": 0, "regime": "UNKNOWN", "belief_hold": 1, "evidence": []})
            else:
                rows.append(self.signal_row(row))
        return pd.concat([out, pd.DataFrame(rows, index=out.index)], axis=1)

    def latest_signal(self, df: pd.DataFrame) -> Dict[str, Any]:
        sigs = self.generate_signals(df)
        return self.signal_row(sigs.iloc[-1])


STRATEGY_CLASS = RegimeKalmanDempsterStrategy
