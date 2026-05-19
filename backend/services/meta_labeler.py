"""
Meta-labelling gate (López de Prado style).

Trains a logistic-regression classifier on closed trades from `trade_history`,
where features are the *metadata* of each signal (confidence, regime, ATR%,
MTF status, time of day, recent win-rate, indicator vote counts, leverage)
and the label is `outcome == "WIN"`.

At entry time the auto-trader builds the same feature vector and asks
`score()` for P(win). The trade is gated by `meta_labeler_threshold` (default
0.45 — slightly below 0.5 so we don't kill trade count, but we drop the worst
candidates).

The model is retrained on demand (`/meta-labeler/retrain` endpoint or after
every N closed trades). Coefficients are persisted in
`meta_labeler_models` so subsequent processes load instantly without retrain.
"""
from __future__ import annotations
import json
import math
from datetime import datetime
from typing import Optional

import numpy as np

from database import db
from services.logger import child as _child_log

_log = _child_log("meta_labeler")
_COL = db["meta_labeler_models"]
_DOC_ID = "current"

REGIMES = ["TRENDING_BULL", "TRENDING_BEAR", "RANGING", "VOLATILE", "QUIET", "UNKNOWN"]
MTF_STATES = ["agree", "disagree", "missing", "off"]
MIN_TRAINING_SAMPLES = 40
DEFAULT_THRESHOLD = 0.45


def _hour_bucket(ts_str: str) -> int:
    """0-23 from ISO timestamp; defaults to 12 if unparseable."""
    if not ts_str:
        return 12
    try:
        return datetime.fromisoformat(str(ts_str).replace("Z", "")).hour
    except Exception:
        return 12


def _onehot(value, options):
    out = [0.0] * len(options)
    if value in options:
        out[options.index(value)] = 1.0
    return out


def _indicator_vote_counts(indicators) -> dict:
    counts = {"buy_votes": 0, "sell_votes": 0, "neutral_votes": 0}
    for ind in indicators or []:
        if not isinstance(ind, dict):
            continue
        sig = str(ind.get("signal", "")).upper()
        if "BUY" in sig:
            counts["buy_votes"] += 1
        elif "SELL" in sig:
            counts["sell_votes"] += 1
        else:
            counts["neutral_votes"] += 1
    return counts


def build_features(trade_or_signal: dict, recent_win_rate: float = 0.5) -> dict:
    """Build the feature dict for either a closed trade row or a live signal.

    Same shape on both sides so training and inference stay in lockstep.
    """
    confidence = float(trade_or_signal.get("confidence", 0) or 0)
    atr = float(trade_or_signal.get("atr") or 0)
    entry = float(trade_or_signal.get("entry_price") or trade_or_signal.get("price") or 0)
    atr_pct = (atr / entry * 100) if entry else 0.0
    leverage = float(trade_or_signal.get("leverage", 1.0) or 1.0)
    direction = "BUY" if "BUY" in str(trade_or_signal.get("signal", "")).upper() else "SELL"
    mtf_status = str(trade_or_signal.get("mtf_status", "missing")).lower()
    if mtf_status not in MTF_STATES:
        mtf_status = "missing"
    regime = trade_or_signal.get("regime") or "UNKNOWN"
    hour = _hour_bucket(trade_or_signal.get("opened_at") or trade_or_signal.get("created_at") or "")
    votes = _indicator_vote_counts(trade_or_signal.get("indicators_at_entry") or trade_or_signal.get("indicators") or [])

    features = {
        "confidence": confidence / 100.0,  # normalised 0..1
        "atr_pct": min(atr_pct, 20.0) / 20.0,
        "leverage": min(leverage, 100.0) / 100.0,
        "is_buy": 1.0 if direction == "BUY" else 0.0,
        "hour_sin": math.sin(2 * math.pi * hour / 24),
        "hour_cos": math.cos(2 * math.pi * hour / 24),
        "recent_win_rate": max(0.0, min(1.0, recent_win_rate)),
        "buy_votes": min(votes["buy_votes"], 20) / 20.0,
        "sell_votes": min(votes["sell_votes"], 20) / 20.0,
        "vote_skew": (votes["buy_votes"] - votes["sell_votes"]) / max(1.0, votes["buy_votes"] + votes["sell_votes"]),
    }
    for r in REGIMES:
        features[f"regime_{r}"] = 1.0 if regime == r else 0.0
    for s in MTF_STATES:
        features[f"mtf_{s}"] = 1.0 if mtf_status == s else 0.0
    return features


def _feature_order(sample_features: dict):
    """Stable, sorted key order so train/infer agree on column layout."""
    return sorted(sample_features.keys())


def _vectorise(features: dict, order: list) -> np.ndarray:
    return np.array([float(features.get(k, 0.0)) for k in order], dtype=float)


async def _recent_win_rate(window: int = 50) -> float:
    hist = await db["trade_history"].find({"outcome": {"$in": ["WIN", "LOSS"]}}).sort("closed_at", -1).limit(window).to_list(window)
    if not hist:
        return 0.5
    wins = sum(1 for t in hist if t.get("outcome") == "WIN")
    return wins / len(hist)


async def train_from_history(min_samples: int = MIN_TRAINING_SAMPLES) -> dict:
    """Fit a logistic regression on `trade_history`. Falls back to a baseline
    model (always predicting current win rate) if scikit-learn is unavailable.
    """
    trades = await db["trade_history"].find({"outcome": {"$in": ["WIN", "LOSS"]}}).sort("closed_at", -1).limit(2000).to_list(2000)
    if len(trades) < min_samples:
        return {"status": "skipped", "reason": f"need {min_samples}+ trades, have {len(trades)}"}

    # Build feature matrix in chronological order so recent_win_rate is causal.
    trades.reverse()
    rolling_wins, rolling_total = [], 0
    samples = []
    labels = []
    for t in trades:
        recent_wr = (sum(rolling_wins) / max(len(rolling_wins), 1)) if rolling_wins else 0.5
        feats = build_features(t, recent_win_rate=recent_wr)
        samples.append(feats)
        labels.append(1 if t.get("outcome") == "WIN" else 0)
        rolling_wins.append(1 if t.get("outcome") == "WIN" else 0)
        if len(rolling_wins) > 50:
            rolling_wins.pop(0)
        rolling_total += 1

    order = _feature_order(samples[0])
    X = np.array([_vectorise(f, order) for f in samples])
    y = np.array(labels)

    try:
        from sklearn.linear_model import LogisticRegression
        from sklearn.preprocessing import StandardScaler
        scaler = StandardScaler()
        Xs = scaler.fit_transform(X)
        model = LogisticRegression(max_iter=300, class_weight="balanced", C=1.0)
        model.fit(Xs, y)
        coef = model.coef_[0].tolist()
        intercept = float(model.intercept_[0])
        means = scaler.mean_.tolist()
        scales = scaler.scale_.tolist()
        # Training metrics (in-sample — for a quick sanity read in the UI; real
        # OOS evaluation is what the walk-forward sees).
        preds = model.predict(Xs)
        acc = float(np.mean(preds == y))
        positive_rate = float(np.mean(y))
        doc = {
            "_id": _DOC_ID,
            "kind": "logreg",
            "feature_order": order,
            "coef": coef,
            "intercept": intercept,
            "mean": means,
            "scale": scales,
            "samples": len(y),
            "positive_rate": round(positive_rate, 4),
            "in_sample_acc": round(acc, 4),
            "updated_at": datetime.utcnow().isoformat(),
        }
    except Exception as e:  # sklearn unavailable / numerical issue → baseline
        _log.warning(f"sklearn fit failed, falling back to baseline: {e}")
        doc = {
            "_id": _DOC_ID,
            "kind": "baseline",
            "feature_order": order,
            "baseline_p": float(np.mean(y)) if len(y) else 0.5,
            "samples": int(len(y)),
            "updated_at": datetime.utcnow().isoformat(),
        }
    await _COL.replace_one({"_id": _DOC_ID}, doc, upsert=True)
    return {"status": "trained", "kind": doc["kind"], "samples": doc["samples"], "in_sample_acc": doc.get("in_sample_acc")}


def _sigmoid(z: float) -> float:
    if z >= 0:
        return 1.0 / (1.0 + math.exp(-z))
    e = math.exp(z)
    return e / (1.0 + e)


async def score(signal_or_trade: dict, recent_win_rate: Optional[float] = None) -> dict:
    """Return {p_win, kind, ready}. p_win in [0, 1]. `ready=False` means the
    model hasn't been trained yet — caller should treat as neutral pass.
    """
    doc = await _COL.find_one({"_id": _DOC_ID})
    if not doc:
        return {"p_win": 0.5, "kind": "untrained", "ready": False}
    if recent_win_rate is None:
        recent_win_rate = await _recent_win_rate()
    feats = build_features(signal_or_trade, recent_win_rate=recent_win_rate)
    order = doc.get("feature_order") or _feature_order(feats)

    if doc.get("kind") == "logreg":
        x = np.array([feats.get(k, 0.0) for k in order], dtype=float)
        mean = np.array(doc.get("mean") or [0.0] * len(order))
        scale = np.array(doc.get("scale") or [1.0] * len(order))
        scale = np.where(scale == 0, 1.0, scale)
        xs = (x - mean) / scale
        coef = np.array(doc.get("coef") or [0.0] * len(order))
        z = float(np.dot(xs, coef) + float(doc.get("intercept", 0.0)))
        return {"p_win": round(_sigmoid(z), 4), "kind": "logreg", "ready": True, "samples": doc.get("samples")}

    # Baseline model
    p = float(doc.get("baseline_p", 0.5))
    return {"p_win": round(p, 4), "kind": "baseline", "ready": True, "samples": doc.get("samples")}


async def should_trade(signal_or_trade: dict, threshold: float = DEFAULT_THRESHOLD, recent_win_rate: Optional[float] = None) -> dict:
    s = await score(signal_or_trade, recent_win_rate=recent_win_rate)
    if not s.get("ready"):
        return {"allow": True, "reason": "model_untrained", **s}
    allow = s["p_win"] >= threshold
    return {"allow": allow, "threshold": threshold, **s}


async def model_info() -> dict:
    doc = await _COL.find_one({"_id": _DOC_ID})
    if not doc:
        return {"trained": False}
    doc.pop("_id", None)
    return {"trained": True, **doc}
