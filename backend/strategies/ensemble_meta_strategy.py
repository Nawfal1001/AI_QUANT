from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Dict, List

import pandas as pd

from backend.strategies.bayesian_voting_strategy import BayesianVotingStrategy


@dataclass
class StrategyVote:
    name: str
    direction: int
    confidence: float
    weight: float
    reason: str


class EnsembleMetaStrategy:
    """
    Advanced meta strategy.

    Instead of voting only with indicators, this votes between strategy families:
    - Bayesian balanced signal
    - trend-regime signal
    - breakout-continuation signal
    - mean-reversion signal
    - optional AutoSignal score from the dataset

    Goal: improve trade confidence by requiring agreement between independent models.
    """

    name = "AI Quant Ensemble Meta Strategy"
    slug = "ensemble_meta"
    description = "Meta-voting strategy combining Bayesian, trend, breakout, mean-reversion and AutoSignal evidence."

    defaults: Dict[str, Any] = {
        "buy_threshold": 0.67,
        "sell_threshold": 0.33,
        "min_confidence": 0.64,
        "agreement_bonus": 0.08,
        "conflict_penalty": 0.12,
        "bayesian_weight": 1.4,
        "trend_regime_weight": 1.3,
        "breakout_weight": 1.1,
        "mean_reversion_weight": 0.9,
        "autosignal_weight": 1.2,
        "adx_trend": 20,
        "volume_breakout": 1.25,
        "risk_reward": 1.9,
        "atr_stop_mult": 1.7,
    }

    def __init__(self, **params: Any):
        self.params = {**self.defaults, **params}
        self.base = BayesianVotingStrategy(**params)

    @staticmethod
    def _f(v: Any, default: float = 0.0) -> float:
        try:
            return float(v)
        except Exception:
            return default

    @staticmethod
    def _posterior(votes: List[StrategyVote]) -> float:
        if not votes:
            return 0.5
        log_odds = 0.0
        for v in votes:
            c = max(0.01, min(0.99, v.confidence))
            log_odds += v.direction * v.weight * math.log(c / (1 - c))
        return 1 / (1 + math.exp(-log_odds))

    def add_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        return self.base.add_indicators(df)

    def _bayesian_vote(self, row: pd.Series) -> StrategyVote:
        sig = self.base.signal_row(row)
        direction = 1 if sig["signal"] == "BUY" else (-1 if sig["signal"] == "SELL" else 0)
        confidence = max(sig.get("prob_long", 0.5), sig.get("prob_short", 0.5))
        return StrategyVote("bayesian_balanced", direction, confidence, self.params["bayesian_weight"], f"Bayesian base signal {sig['signal']}")

    def _trend_vote(self, row: pd.Series) -> StrategyVote:
        p = self.params
        adx = self._f(row.get("adx"))
        if adx < p["adx_trend"]:
            return StrategyVote("trend_regime", 0, 0.5, p["trend_regime_weight"], "No strong trend regime")
        if row["close"] > row["ema_trend"] and row["ema_fast"] > row["ema_slow"]:
            return StrategyVote("trend_regime", 1, min(0.82, 0.55 + adx / 100), p["trend_regime_weight"], "Confirmed bullish trend regime")
        if row["close"] < row["ema_trend"] and row["ema_fast"] < row["ema_slow"]:
            return StrategyVote("trend_regime", -1, min(0.82, 0.55 + adx / 100), p["trend_regime_weight"], "Confirmed bearish trend regime")
        return StrategyVote("trend_regime", 0, 0.5, p["trend_regime_weight"], "Mixed trend regime")

    def _breakout_vote(self, row: pd.Series) -> StrategyVote:
        p = self.params
        vol_ok = self._f(row.get("volume_ratio")) >= p["volume_breakout"]
        if row["close"] > row.get("breakout_high", float("inf")) and vol_ok:
            return StrategyVote("breakout_continuation", 1, 0.7, p["breakout_weight"], "Bullish breakout with volume")
        if row["close"] < row.get("breakout_low", -float("inf")) and vol_ok:
            return StrategyVote("breakout_continuation", -1, 0.7, p["breakout_weight"], "Bearish breakout with volume")
        return StrategyVote("breakout_continuation", 0, 0.5, p["breakout_weight"], "No confirmed breakout")

    def _mean_reversion_vote(self, row: pd.Series) -> StrategyVote:
        p = self.params
        adx = self._f(row.get("adx"))
        if adx >= p["adx_trend"] + 5:
            return StrategyVote("mean_reversion", 0, 0.5, p["mean_reversion_weight"], "Mean reversion disabled in strong trend")
        if row["bb_pos"] < 0.15 and row["rsi"] < 35:
            return StrategyVote("mean_reversion", 1, 0.66, p["mean_reversion_weight"], "Oversold range reversion")
        if row["bb_pos"] > 0.85 and row["rsi"] > 65:
            return StrategyVote("mean_reversion", -1, 0.66, p["mean_reversion_weight"], "Overbought range reversion")
        return StrategyVote("mean_reversion", 0, 0.5, p["mean_reversion_weight"], "No mean-reversion edge")

    def _autosignal_vote(self, row: pd.Series) -> StrategyVote:
        p = self.params
        raw = str(row.get("autosignal", row.get("auto_signal", ""))).upper()
        score = self._f(row.get("autosignal_score", row.get("auto_signal_score", row.get("confidence", 0))))
        if score > 1:
            score = score / 100
        score = max(0.5, min(0.9, score or 0.5))
        if "BUY" in raw or "LONG" in raw:
            return StrategyVote("autosignal", 1, score, p["autosignal_weight"], "AutoSignal bullish confirmation")
        if "SELL" in raw or "SHORT" in raw:
            return StrategyVote("autosignal", -1, score, p["autosignal_weight"], "AutoSignal bearish confirmation")
        return StrategyVote("autosignal", 0, 0.5, p["autosignal_weight"], "No AutoSignal confirmation")

    def signal_row(self, row: pd.Series) -> Dict[str, Any]:
        p = self.params
        raw_votes = [
            self._bayesian_vote(row),
            self._trend_vote(row),
            self._breakout_vote(row),
            self._mean_reversion_vote(row),
            self._autosignal_vote(row),
        ]
        votes = [v for v in raw_votes if v.direction != 0]
        prob_long = self._posterior(votes)
        directions = [v.direction for v in votes]
        if directions:
            majority = 1 if directions.count(1) > directions.count(-1) else -1 if directions.count(-1) > directions.count(1) else 0
            agreement = max(directions.count(1), directions.count(-1)) / len(directions)
            if agreement >= 0.75 and majority == 1:
                prob_long = min(0.97, prob_long + p["agreement_bonus"])
            elif agreement >= 0.75 and majority == -1:
                prob_long = max(0.03, prob_long - p["agreement_bonus"])
            elif agreement < 0.6:
                prob_long = 0.5 + (prob_long - 0.5) * (1 - p["conflict_penalty"])
        prob_short = 1 - prob_long
        confidence = max(prob_long, prob_short)
        signal = "HOLD"
        if prob_long >= p["buy_threshold"] and confidence >= p["min_confidence"]:
            signal = "BUY"
        elif prob_long <= p["sell_threshold"] and confidence >= p["min_confidence"]:
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
            "prob_long": round(prob_long, 4),
            "prob_short": round(prob_short, 4),
            "confidence": round(confidence * 100, 2),
            "price": round(price, 6),
            "sl": round(sl, 6) if sl is not None else None,
            "tp": round(tp, 6) if tp is not None else None,
            "strategy_votes": [v.__dict__ for v in raw_votes],
            "active_votes": len(votes),
        }

    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        out = self.add_indicators(df)
        rows = []
        for _, row in out.iterrows():
            if row.isna().any():
                rows.append({"signal": "HOLD", "prob_long": 0.5, "confidence": 0, "strategy_votes": []})
            else:
                rows.append(self.signal_row(row))
        return pd.concat([out, pd.DataFrame(rows, index=out.index)], axis=1)

    def latest_signal(self, df: pd.DataFrame) -> Dict[str, Any]:
        sigs = self.generate_signals(df)
        return self.signal_row(sigs.iloc[-1])


STRATEGY_CLASS = EnsembleMetaStrategy
