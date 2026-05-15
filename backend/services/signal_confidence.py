"""
Signal Confidence Calibration.

Turns raw strategy confidence into a more realistic confidence score by combining:
- raw strategy confidence
- adaptive selector score
- local regime confidence
- macro alignment or conflict
- historical signal/trade edge
- uncertainty penalties

The goal is to avoid fake confidence and only boost when independent factors agree.
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
    out = {"score": 50.0, "confidence": 0.0, "reason": "no matching history"}
    try:
        stat = await db["signal_stats"].find_one({
            "user_id": user_id,
            "strategy": strategy,
            "ticker": ticker,
            "timeframe": timeframe,
            "regime": regime,
        })
        if stat and int(stat.get("total", 0) or 0) >= MIN_HISTORY_SIGNALS:
            total = int(stat.get("total", 0) or 0)
            wr = float(stat.get("win_rate", 50) or 50)
            avg = float(stat.get("avg_pnl_pct", 0) or 0)
            score = _clamp(wr * 0.75 + _clamp(50 + avg * 10) * 0.25)
            out = {"score": score, "confidence": min(90, total * 4), "reason": f"signal history wr={wr:.1f}% avg={avg:.2f}% n={total}"}
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
            if out["confidence"] > 0:
                out["score"] = out["score"] * 0.45 + score * 0.55
                out["confidence"] = max(out["confidence"], min(95, len(trades) * 6))
                out["reason"] += f"; trade history wr={wr:.1f}% avg={avg:.2f}% n={len(trades)}"
            else:
                out = {"score": score, "confidence": min(95, len(trades) * 6), "reason": f"trade history wr={wr:.1f}% avg={avg:.2f}% n={len(trades)}"}
    except Exception as e:
        log.debug(f"trade history lookup failed: {e}")
    return out


def _macro_alignment(signal: Dict[str, Any]) -> Dict[str, Any]:
    macro = signal.get("macro") or {}
    action = macro.get("adjustment_action", "neutral")
    conf = float(macro.get("confidence", 0) or 0)
    if action == "boost":
        return {"score": _clamp(55 + conf * 0.35), "weight": min(0.20, conf / 500), "reason": "macro aligned"}
    if action == "reduce":
        return {"score": _clamp(45 - conf * 0.35), "weight": min(0.25, conf / 450), "reason": "macro conflict"}
    return {"score": 50.0, "weight": 0.0, "reason": "macro neutral"}


async def calibrate_signal_confidence(user_id: str, ticker: str, asset_type: str, signal: Dict[str, Any], bot: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    out = dict(signal or {})
    raw_conf = float(out.get("confidence", 0) or 0)
    if _side(out.get("signal")) == "hold":
        out["confidence"] = min(raw_conf, 25)
        out["calibration"] = {"raw_confidence": raw_conf, "calibrated_confidence": out["confidence"], "reason": "hold signal"}
        return out

    strategy = out.get("strategy_used") or (bot or {}).get("strategy_id", "unknown")
    timeframe = out.get("timeframe") or (bot or {}).get("schedule", "1h")
    regime = out.get("regime", "unknown")
    regime_conf = float(out.get("regime_confidence", 50) or 50)
    selector = out.get("selector") or {}
    selector_score = float(selector.get("selected_score") or selector.get("configured_score") or 50)
    history = await _historical_edge(user_id, strategy, ticker, timeframe, regime)
    macro = _macro_alignment(out)

    raw_score = _clamp(raw_conf)
    regime_score = _clamp(regime_conf)
    selector_score = _clamp(selector_score)
    history_weight = 0.22 if history["confidence"] >= 40 else 0.08 if history["confidence"] > 0 else 0.0
    macro_weight = macro["weight"]
    base_weight = 0.42
    selector_weight = 0.18
    regime_weight = 0.12
    total_weight = base_weight + selector_weight + regime_weight + history_weight + macro_weight
    calibrated = (
        raw_score * base_weight +
        selector_score * selector_weight +
        regime_score * regime_weight +
        history["score"] * history_weight +
        macro["score"] * macro_weight
    ) / max(total_weight, 1e-9)

    penalties = []
    if history["confidence"] == 0 and raw_conf > 75:
        calibrated -= 6
        penalties.append("high raw confidence without matching history")
    if regime_conf < 45:
        calibrated -= 5
        penalties.append("weak regime confidence")
    if macro["reason"] == "macro conflict":
        calibrated -= 4
        penalties.append("macro conflict penalty")

    calibrated = _clamp(calibrated)
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
        "penalties": penalties,
    }
    if out["confidence"] < 45:
        out["signal"] = "HOLD"
        out["reason"] = f"confidence calibration blocked weak edge; {out.get('reason', '')}".strip()
    return out
