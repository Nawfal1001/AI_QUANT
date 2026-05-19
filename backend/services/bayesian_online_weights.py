"""
Bayesian online indicator weights with exponential decay.

For every (regime, indicator, vote_direction), maintain Beta(alpha, beta).
On each closed trade, look at which indicators voted in the trade's direction:

    - decay current alpha, beta by `decay_factor` (recency weighting)
    - add +1 to alpha if the trade was a WIN, else +1 to beta

The posterior mean alpha/(alpha+beta) is the indicator's recent reliability for
that regime+direction. Use `score_indicators()` to multiply the live signal's
confidence by a calibrated reliability factor before the auto-trader gates it.

Storage: `bayesian_online_weights` collection, single doc keyed by
{regime: {indicator: {"BUY":{alpha,beta}, "SELL":{alpha,beta}}}}.
"""
from __future__ import annotations
from datetime import datetime
from typing import Optional

from database import db
from services.logger import child as _child_log

_log = _child_log("bayesian_online_weights")
_COL = db["bayesian_online_weights"]
_DOC_ID = "weights"

# Tunables (could be promoted to settings later)
DECAY_FACTOR = 0.985   # ~46-trade half-life: 0.985^46 ≈ 0.5
PRIOR_ALPHA = 4.0       # weakly informative — Beta(4,4) ⇒ prior mean 0.5
PRIOR_BETA = 4.0
MIN_TRIALS = 6          # below this, indicator's posterior is ignored (use 1.0)


def _empty_state():
    return {"_id": _DOC_ID, "data": {}, "updated_at": datetime.utcnow().isoformat()}


async def _load():
    doc = await _COL.find_one({"_id": _DOC_ID})
    return doc or _empty_state()


async def _save(state):
    state["updated_at"] = datetime.utcnow().isoformat()
    await _COL.replace_one({"_id": _DOC_ID}, state, upsert=True)


def _bucket(state, regime, indicator, direction):
    data = state.setdefault("data", {})
    reg = data.setdefault(regime or "UNKNOWN", {})
    ind = reg.setdefault(indicator, {})
    return ind.setdefault(direction, {"alpha": PRIOR_ALPHA, "beta": PRIOR_BETA, "n": 0})


def _direction_from_signal(signal: str) -> Optional[str]:
    s = (signal or "").upper()
    if "BUY" in s:
        return "BUY"
    if "SELL" in s:
        return "SELL"
    return None


def _indicator_voted(ind_sig: str, trade_dir: str) -> bool:
    """True iff this indicator's signal points in the trade's direction."""
    s = (ind_sig or "").upper()
    if not s or s in {"NEUTRAL", "INFO", "ALERT", "HOLD", "PENDING"}:
        return False
    if trade_dir == "BUY" and "BUY" in s:
        return True
    if trade_dir == "SELL" and "SELL" in s:
        return True
    return False


async def update_from_trade(trade: dict) -> dict:
    """Update Beta posteriors for every indicator that voted the trade's direction.

    Idempotent-by-trade is the caller's responsibility — call once per closed
    trade. WIN ⇒ +1 to alpha, LOSS ⇒ +1 to beta; both buckets are first decayed
    so recency dominates older samples.
    """
    direction = _direction_from_signal(trade.get("signal"))
    if direction is None:
        return {"updated": 0, "reason": "no_direction"}

    indicators = trade.get("indicators_at_entry") or []
    if not indicators:
        return {"updated": 0, "reason": "no_indicators"}

    outcome = (trade.get("outcome") or "").upper()
    if outcome not in {"WIN", "LOSS"}:
        return {"updated": 0, "reason": f"non_terminal_outcome:{outcome}"}

    regime = trade.get("regime") or "UNKNOWN"
    state = await _load()

    updates = 0
    for ind in indicators:
        if not isinstance(ind, dict):
            continue
        name = ind.get("indicator")
        ind_sig = ind.get("signal", "")
        if not name or not _indicator_voted(ind_sig, direction):
            continue
        b = _bucket(state, regime, name, direction)
        # Exponential decay first — past samples lose weight.
        b["alpha"] = b["alpha"] * DECAY_FACTOR
        b["beta"] = b["beta"] * DECAY_FACTOR
        if outcome == "WIN":
            b["alpha"] += 1.0
        else:
            b["beta"] += 1.0
        b["n"] = int(b.get("n", 0)) + 1
        updates += 1

    if updates:
        await _save(state)
    return {"updated": updates, "regime": regime, "direction": direction, "outcome": outcome}


async def posterior_mean(regime: str, indicator: str, direction: str) -> Optional[float]:
    """Return posterior mean alpha/(alpha+beta) or None if too few samples."""
    state = await _load()
    bucket = state.get("data", {}).get(regime or "UNKNOWN", {}).get(indicator, {}).get(direction)
    if not bucket or int(bucket.get("n", 0)) < MIN_TRIALS:
        return None
    a, b = float(bucket["alpha"]), float(bucket["beta"])
    if a + b <= 0:
        return None
    return a / (a + b)


async def confidence_multiplier(regime: str, direction: str, indicators: list) -> dict:
    """Compute a [0.7, 1.2] confidence multiplier for a live signal based on
    the posterior reliability of the indicators that voted its direction.

    Indicators with <MIN_TRIALS samples in this (regime, direction) cell are
    treated as neutral (multiplier 1.0). Indicators that have been historically
    *wrong* in this cell (posterior < 0.4) drag the multiplier down; indicators
    that have been *right* (posterior > 0.6) push it up.
    """
    if direction not in {"BUY", "SELL"} or not indicators:
        return {"multiplier": 1.0, "evaluated": 0, "boost_terms": [], "drag_terms": []}

    state = await _load()
    cell = state.get("data", {}).get(regime or "UNKNOWN", {})
    contribs = []
    boost_terms, drag_terms = [], []
    for ind in indicators:
        if not isinstance(ind, dict):
            continue
        name = ind.get("indicator")
        ind_sig = ind.get("signal", "")
        if not name or not _indicator_voted(ind_sig, direction):
            continue
        bucket = cell.get(name, {}).get(direction)
        if not bucket or int(bucket.get("n", 0)) < MIN_TRIALS:
            continue
        a, b = float(bucket["alpha"]), float(bucket["beta"])
        p = a / (a + b) if (a + b) > 0 else 0.5
        contribs.append(p)
        term = {"indicator": name, "p": round(p, 3), "n": int(bucket["n"])}
        if p >= 0.6:
            boost_terms.append(term)
        elif p <= 0.4:
            drag_terms.append(term)

    if not contribs:
        return {"multiplier": 1.0, "evaluated": 0, "boost_terms": [], "drag_terms": []}

    avg = sum(contribs) / len(contribs)
    # Map [0.3, 0.7] reliability → [0.7, 1.2] multiplier (linear, then clamped).
    mult = 0.7 + (avg - 0.3) * (0.5 / 0.4)
    mult = max(0.7, min(1.2, mult))
    return {
        "multiplier": round(mult, 4),
        "evaluated": len(contribs),
        "avg_posterior": round(avg, 4),
        "boost_terms": boost_terms,
        "drag_terms": drag_terms,
    }


async def snapshot() -> dict:
    """Read-only view of the current posterior table (for UI/inspection)."""
    state = await _load()
    out = {}
    for regime, inds in (state.get("data") or {}).items():
        out[regime] = {}
        for name, dirs in inds.items():
            out[regime][name] = {}
            for d, b in dirs.items():
                a, beta = float(b.get("alpha", 0)), float(b.get("beta", 0))
                p = a / (a + beta) if (a + beta) > 0 else None
                out[regime][name][d] = {
                    "alpha": round(a, 3),
                    "beta": round(beta, 3),
                    "n": int(b.get("n", 0)),
                    "posterior": round(p, 4) if p is not None else None,
                }
    return {"data": out, "updated_at": state.get("updated_at")}
