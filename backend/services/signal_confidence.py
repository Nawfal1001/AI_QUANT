"""
Signal Confidence Calibration.

Improved calibrator that separates:
- noisy high-confidence signals
- new but strongly confirmed emerging edges
- historically proven edges
- conflicting/weak edges

It uses agreement scoring, edge classification, confidence ceilings, and
conditional penalties so missing history is neutral unless other confirmations
are also weak.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from database import db
from services.logger import child

log = child("signal_confidence")

MIN_HISTORY_SIGNALS = 8
MIN_HISTORY_TRADES = 5


def _clamp(x: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, x))


def _side(signal: str) -> str:
    s = (signal or "HOLD").upper()
    if "BUY" in s:
        return "buy"
    if "SELL" in s:
        return "sell"
    return "hold"


async def _historical_edge(user_id: str, strategy: str, ticker: str, timeframe: str, regime: str) -> Dict[str, Any]:
    out = {"score": 50.0, "confidence": 0.0, "sample_size": 0, "class": "unknown", "reason": "no matching history"}
    try:
        stat = await db["signal_stats"].find_one({"user_id": user_id, "strategy": strategy, "ticker": ticker, "timeframe": timeframe, "regime": regime})
        if stat and int(stat.get("total", 0) or 0) >= MIN_HISTORY_SIGNALS:
            total = int(stat.get("total", 0) or 0)
            wr = float(stat.get("win_rate", 50) or 50)
            avg = float(stat.get("avg_pnl_pct", 0) or 0)
            score = _clamp(wr * 0.75 + _clamp(50 + avg * 10) * 0.25)
            klass = "good" if score >= 60 else "bad" if score <= 45 else "mixed"
            out = {"score": score, "confidence": min(90, total * 4), "sample_size": total, "class": klass, "reason": f"signal history wr={wr:.1f}% avg={avg:.2f}% n={total}"}
    except Exception as e:
        log.debug(f"signal history lookup failed: {e}")
    try:
        q = {"user_id": user_id, "strategy": strategy, "ticker": ticker, "timeframe": timeframe, "regime": regime, "status": "closed"}
        trades = await db["trades"].find(q).sort("closed_at", -1).limit(50).to_list(50)
        if len(trades) >= MIN_HISTORY_TRADES:
            wins = [t for t in trades if float(t.get("pnl", t.get("realized_pnl", 0)) or 0) > 0]
            wr = len(wins) / len(trades) * 100
            pnls = [float(t.get("pnl_pct", 0) or 0) for t in trades]
            avg = sum(pnls) / len(pnls) if pnls else 0
            score = _clamp(wr * 0.7 + _clamp(50 + avg * 10) * 0.3)
            klass = "good" if score >= 60 else "bad" if score <= 45 else "mixed"
            if out["confidence"] > 0:
                out["score"] = out["score"] * 0.45 + score * 0.55
                out["confidence"] = max(out["confidence"], min(95, len(trades) * 6))
                out["sample_size"] += len(trades)
                out["class"] = "good" if out["score"] >= 60 else "bad" if out["score"] <= 45 else "mixed"
                out["reason"] += f"; trade history wr={wr:.1f}% avg={avg:.2f}% n={len(trades)}"
            else:
                out = {"score": score, "confidence": min(95, len(trades) * 6), "sample_size": len(trades), "class": klass, "reason": f"trade history wr={wr:.1f}% avg={avg:.2f}% n={len(trades)}"}
    except Exception as e:
        log.debug(f"trade history lookup failed: {e}")
    return out


def _macro_alignment(signal: Dict[str, Any]) -> Dict[str, Any]:
    macro = signal.get("macro") or {}
    action = macro.get("adjustment_action", "neutral")
    conf = float(macro.get("confidence", 0) or 0)
    if action == "boost":
        return {"score": _clamp(55 + conf * 0.35), "weight": min(0.20, conf / 500), "state": "aligned", "reason": "macro aligned"}
    if action == "reduce":
        return {"score": _clamp(45 - conf * 0.35), "weight": min(0.25, conf / 450), "state": "conflict", "reason": "macro conflict"}
    return {"score": 50.0, "weight": 0.0, "state": "neutral", "reason": "macro neutral"}


def _agreement_score(raw_conf: float, selector_score: float, regime_conf: float, history: Dict[str, Any], macro: Dict[str, Any]) -> Dict[str, Any]:
    points = 0.0
    max_points = 0.0
    reasons = []

    max_points += 1.0
    if raw_conf >= 70:
        points += 1.0
        reasons.append("raw strategy strong")
    elif raw_conf >= 58:
        points += 0.55
        reasons.append("raw strategy acceptable")

    max_points += 1.0
    if selector_score >= 68:
        points += 1.0
        reasons.append("selector strong")
    elif selector_score >= 55:
        points += 0.55
        reasons.append("selector acceptable")

    max_points += 1.0
    if regime_conf >= 68:
        points += 1.0
        reasons.append("regime strong")
    elif regime_conf >= 55:
        points += 0.55
        reasons.append("regime acceptable")

    max_points += 1.0
    if history["class"] == "good":
        points += 1.0
        reasons.append("history good")
    elif history["class"] == "mixed":
        points += 0.45
        reasons.append("history mixed")
    elif history["class"] == "unknown":
        points += 0.35
        reasons.append("history unknown-neutral")

    max_points += 1.0
    if macro["state"] == "aligned":
        points += 1.0
        reasons.append("macro aligned")
    elif macro["state"] == "neutral":
        points += 0.45
        reasons.append("macro neutral")

    score = _clamp((points / max_points) * 100 if max_points else 50)
    return {"score": round(score, 2), "points": round(points, 2), "max_points": max_points, "reasons": reasons}


def _classify_edge(agreement: Dict[str, Any], history: Dict[str, Any], macro: Dict[str, Any], raw_conf: float, regime_conf: float, selector_score: float) -> str:
    agree = agreement["score"]
    if macro["state"] == "conflict" and agree < 65:
        return "conflicting_edge"
    if history["class"] == "bad":
        return "historically_bad_edge"
    if history["class"] == "good" and agree >= 62:
        return "proven_edge"
    if history["class"] == "unknown" and agree >= 68 and raw_conf >= 68 and regime_conf >= 55 and selector_score >= 55:
        return "emerging_edge"
    if agree >= 58:
        return "unconfirmed_edge"
    return "noisy_or_weak_edge"


def _confidence_ceiling(edge_class: str, agreement_score: float, history: Dict[str, Any], macro: Dict[str, Any]) -> float:
    if edge_class == "proven_edge":
        return 92.0 if history["confidence"] >= 60 else 86.0
    if edge_class == "emerging_edge":
        return 80.0 if agreement_score >= 78 else 76.0
    if edge_class == "unconfirmed_edge":
        return 68.0
    if edge_class == "historically_bad_edge":
        return 56.0
    if edge_class == "conflicting_edge":
        return 52.0 if macro["state"] == "conflict" else 58.0
    return 60.0


async def calibrate_signal_confidence(user_id: str, ticker: str, asset_type: str, signal: Dict[str, Any], bot: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    out = dict(signal or {})
    raw_conf = float(out.get("confidence", 0) or 0)
    if _side(out.get("signal")) == "hold":
        out["confidence"] = min(raw_conf, 25)
        out["calibration"] = {"raw_confidence": raw_conf, "calibrated_confidence": out["confidence"], "edge_class": "hold", "reason": "hold signal"}
        return out

    strategy = out.get("strategy_used") or (bot or {}).get("strategy_id", "unknown")
    timeframe = out.get("timeframe") or (bot or {}).get("schedule", "1h")
    regime = out.get("regime", "unknown")
    regime_conf = float(out.get("regime_confidence", 50) or 50)
    selector = out.get("selector") or {}
    selector_score = float(selector.get("selected_score") or selector.get("configured_score") or 50)
    history = await _historical_edge(user_id, strategy, ticker, timeframe, regime)
    macro = _macro_alignment(out)
    agreement = _agreement_score(raw_conf, selector_score, regime_conf, history, macro)
    edge_class = _classify_edge(agreement, history, macro, raw_conf, regime_conf, selector_score)

    raw_score = _clamp(raw_conf)
    regime_score = _clamp(regime_conf)
    selector_score = _clamp(selector_score)
    history_weight = 0.24 if history["confidence"] >= 40 else 0.08 if history["confidence"] > 0 else 0.0
    macro_weight = macro["weight"]
    agreement_weight = 0.16
    base_weight = 0.36
    selector_weight = 0.16
    regime_weight = 0.10
    total_weight = base_weight + selector_weight + regime_weight + history_weight + macro_weight + agreement_weight
    calibrated = (
        raw_score * base_weight +
        selector_score * selector_weight +
        regime_score * regime_weight +
        history["score"] * history_weight +
        macro["score"] * macro_weight +
        agreement["score"] * agreement_weight
    ) / max(total_weight, 1e-9)

    penalties = []
    boosts = []
    if edge_class == "emerging_edge":
        calibrated += 4
        boosts.append("emerging edge allowed despite missing history")
    if edge_class == "proven_edge":
        calibrated += 3
        boosts.append("proven historical edge")
    if history["class"] == "unknown" and raw_conf > 75 and agreement["score"] < 58:
        calibrated -= 8
        penalties.append("high raw confidence without agreement or history")
    if regime_conf < 45:
        calibrated -= 5
        penalties.append("weak regime confidence")
    if macro["state"] == "conflict":
        calibrated -= 4 if agreement["score"] >= 68 else 8
        penalties.append("macro conflict penalty")
    if history["class"] == "bad":
        calibrated -= 8
        penalties.append("bad historical edge penalty")

    ceiling = _confidence_ceiling(edge_class, agreement["score"], history, macro)
    calibrated = min(_clamp(calibrated), ceiling)
    out["confidence"] = round(calibrated, 2)
    out["calibration"] = {
        "raw_confidence": raw_conf,
        "calibrated_confidence": out["confidence"],
        "strategy": strategy,
        "timeframe": timeframe,
        "regime": regime,
        "selector_score": selector_score,
        "regime_confidence": regime_conf,
        "history": history,
        "macro": macro,
        "agreement": agreement,
        "edge_class": edge_class,
        "confidence_ceiling": ceiling,
        "boosts": boosts,
        "penalties": penalties,
    }
    if out["confidence"] < 45 or edge_class in {"noisy_or_weak_edge", "conflicting_edge"} and out["confidence"] < 55:
        out["signal"] = "HOLD"
        out["reason"] = f"confidence calibration blocked {edge_class}; {out.get('reason', '')}".strip()
    return out
