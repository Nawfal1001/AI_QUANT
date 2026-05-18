from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import pandas as pd


@dataclass
class Vote:
    name: str
    direction: int
    confidence: float
    weight: float
    reason: str


class BayesianVotingStrategy:
    """
    Standalone strategy template for Strategy Lab / backtests.

    The strategy converts indicator evidence into weighted Bayesian-style votes.
    It is intentionally deterministic and optimizer-friendly: every threshold and
    weight can be exposed in Strategy Lab later.
    """

    name = "Bayesian Voting Strategy"
    slug = "bayesian_voting"
    description = "Weighted Bayesian vote model using trend, momentum, volatility, volume and breakout evidence."

    defaults: Dict[str, Any] = {
        "rsi_buy": 55,
        "rsi_sell": 45,
        "rsi_overbought": 72,
        "rsi_oversold": 28,
        "ema_fast": 12,
        "ema_slow": 26,
        "ema_trend": 200,
        "macd_fast": 12,
        "macd_slow": 26,
        "macd_signal": 9,
        "bb_period": 20,
        "bb_std": 2.0,
        "atr_period": 14,
        "adx_period": 14,
        "adx_trend": 20,
        "volume_period": 20,
        "breakout_period": 20,
        "buy_threshold": 0.62,
        "sell_threshold": 0.38,
        "min_confidence": 0.58,
        "trend_weight": 1.4,
        "momentum_weight": 1.2,
        "macd_weight": 1.1,
        "volatility_weight": 0.8,
        "volume_weight": 0.7,
        "breakout_weight": 1.0,
        "risk_reward": 1.8,
        "atr_stop_mult": 1.6,
    }

    def __init__(self, **params: Any):
        self.params = {**self.defaults, **params}

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
    def _adx(df: pd.DataFrame, n: int = 14) -> pd.Series:
        high, low, close = df["high"], df["low"], df["close"]
        plus_dm = (high.diff()).where((high.diff() > -low.diff()) & (high.diff() > 0), 0.0)
        minus_dm = (-low.diff()).where((-low.diff() > high.diff()) & (-low.diff() > 0), 0.0)
        tr = pd.concat([(high - low), (high - close.shift()).abs(), (low - close.shift()).abs()], axis=1).max(axis=1)
        atr = tr.rolling(n).mean().replace(0, float("nan"))
        plus_di = 100 * plus_dm.rolling(n).mean() / atr
        minus_di = 100 * minus_dm.rolling(n).mean() / atr
        dx = ((plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, float("nan"))) * 100
        return dx.rolling(n).mean()

    def add_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        p = self.params
        out = df.copy()
        out.columns = [c.lower() for c in out.columns]
        out["ema_fast"] = self._ema(out["close"], p["ema_fast"])
        out["ema_slow"] = self._ema(out["close"], p["ema_slow"])
        out["ema_trend"] = self._ema(out["close"], p["ema_trend"])
        out["rsi"] = self._rsi(out["close"], 14)
        macd = self._ema(out["close"], p["macd_fast"]) - self._ema(out["close"], p["macd_slow"])
        out["macd"] = macd
        out["macd_signal"] = self._ema(macd, p["macd_signal"])
        out["macd_hist"] = out["macd"] - out["macd_signal"]
        mid = out["close"].rolling(p["bb_period"]).mean()
        std = out["close"].rolling(p["bb_period"]).std()
        out["bb_mid"] = mid
        out["bb_upper"] = mid + p["bb_std"] * std
        out["bb_lower"] = mid - p["bb_std"] * std
        out["bb_pos"] = (out["close"] - out["bb_lower"]) / (out["bb_upper"] - out["bb_lower"]).replace(0, float("nan"))
        out["atr"] = self._atr(out, p["atr_period"])
        out["adx"] = self._adx(out, p["adx_period"])
        out["volume_ma"] = out.get("volume", pd.Series(index=out.index, data=0)).rolling(p["volume_period"]).mean()
        out["volume_ratio"] = out.get("volume", pd.Series(index=out.index, data=0)) / out["volume_ma"].replace(0, float("nan"))
        out["breakout_high"] = out["high"].rolling(p["breakout_period"]).max().shift(1)
        out["breakout_low"] = out["low"].rolling(p["breakout_period"]).min().shift(1)
        return out

    def _votes_for_row(self, row: pd.Series) -> List[Vote]:
        p = self.params
        votes: List[Vote] = []
        if row["ema_fast"] > row["ema_slow"] and row["close"] > row["ema_trend"]:
            votes.append(Vote("trend", 1, min(0.95, 0.55 + row.get("adx", 0) / 100), p["trend_weight"], "fast EMA above slow and above trend EMA"))
        elif row["ema_fast"] < row["ema_slow"] and row["close"] < row["ema_trend"]:
            votes.append(Vote("trend", -1, min(0.95, 0.55 + row.get("adx", 0) / 100), p["trend_weight"], "fast EMA below slow and below trend EMA"))
        if row["rsi"] >= p["rsi_buy"] and row["rsi"] < p["rsi_overbought"]:
            votes.append(Vote("rsi_momentum", 1, min(0.92, row["rsi"] / 100), p["momentum_weight"], "RSI bullish momentum"))
        elif row["rsi"] <= p["rsi_sell"] and row["rsi"] > p["rsi_oversold"]:
            votes.append(Vote("rsi_momentum", -1, min(0.92, (100 - row["rsi"]) / 100), p["momentum_weight"], "RSI bearish momentum"))
        if row["macd_hist"] > 0 and row["macd"] > row["macd_signal"]:
            votes.append(Vote("macd", 1, 0.62, p["macd_weight"], "MACD histogram positive"))
        elif row["macd_hist"] < 0 and row["macd"] < row["macd_signal"]:
            votes.append(Vote("macd", -1, 0.62, p["macd_weight"], "MACD histogram negative"))
        if row["bb_pos"] < 0.18 and row["rsi"] < 45:
            votes.append(Vote("mean_reversion", 1, 0.58, p["volatility_weight"], "near lower Bollinger band"))
        elif row["bb_pos"] > 0.82 and row["rsi"] > 55:
            votes.append(Vote("mean_reversion", -1, 0.58, p["volatility_weight"], "near upper Bollinger band"))
        if row.get("volume_ratio", 0) > 1.2:
            direction = 1 if row["close"] > row["open"] else -1
            votes.append(Vote("volume_confirmation", direction, min(0.8, 0.5 + row["volume_ratio"] / 10), p["volume_weight"], "volume expansion confirms candle direction"))
        if row["close"] > row.get("breakout_high", float("inf")):
            votes.append(Vote("breakout", 1, 0.68, p["breakout_weight"], "close above prior range high"))
        elif row["close"] < row.get("breakout_low", -float("inf")):
            votes.append(Vote("breakout", -1, 0.68, p["breakout_weight"], "close below prior range low"))
        return votes

    @staticmethod
    def _posterior(votes: List[Vote]) -> float:
        if not votes:
            return 0.5
        log_odds = 0.0
        for v in votes:
            c = max(0.01, min(0.99, v.confidence))
            log_odds += v.direction * v.weight * math.log(c / (1 - c))
        return 1 / (1 + math.exp(-log_odds))

    def signal_row(self, row: pd.Series) -> Dict[str, Any]:
        p = self.params
        votes = self._votes_for_row(row)
        prob_long = self._posterior(votes)
        prob_short = 1 - prob_long
        confidence = max(prob_long, prob_short)
        signal = "HOLD"
        if prob_long >= p["buy_threshold"] and confidence >= p["min_confidence"]:
            signal = "BUY"
        elif prob_long <= p["sell_threshold"] and confidence >= p["min_confidence"]:
            signal = "SELL"
        atr = _f(row.get("atr"), _f(row.get("close")) * 0.02)
        price = _f(row.get("close"))
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
            "prob_long": round(prob_long, 4),
            "prob_short": round(prob_short, 4),
            "confidence": round(confidence * 100, 2),
            "price": round(price, 6),
            "sl": round(sl, 6) if sl is not None else None,
            "tp": round(tp, 6) if tp is not None else None,
            "atr": round(atr, 6),
            "votes": [v.__dict__ for v in votes],
        }

    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        out = self.add_indicators(df)
        rows = []
        for _, row in out.iterrows():
            if row.isna().any():
                rows.append({"signal": "HOLD", "prob_long": 0.5, "confidence": 0, "votes": []})
            else:
                rows.append(self.signal_row(row))
        sigs = pd.DataFrame(rows, index=out.index)
        return pd.concat([out, sigs], axis=1)

    def latest_signal(self, df: pd.DataFrame) -> Dict[str, Any]:
        sigs = self.generate_signals(df)
        return self.signal_row(sigs.iloc[-1])


STRATEGY_CLASS = BayesianVotingStrategy
