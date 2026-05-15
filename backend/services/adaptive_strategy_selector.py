"""
Adaptive Strategy Selector.

Learns which strategy works best for each (ticker, timeframe, regime) context.
It is intentionally conservative:
- If there is not enough evidence, it keeps the bot's configured strategy.
- If all candidates have negative expected value, it can recommend NO_TRADE.
- It can use both signal_stats and paper closed trades when available.

This service is safe to use during paper trading and backtesting. It does not place
orders; it only returns a recommendation for the bot runner or backtest layer.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional

from database import db
from services.logger import child
from services.strategies import STRATEGIES

log = child("adaptive_selector")

col_signal_stats = db["signal_stats"]
col_trades = db["trades"]
col_selector_decisions = db["adaptive_selector_decisions"]

MIN_SIGNAL_SAMPLES = 8
MIN_TRADE_SAMPLES = 5
MIN_SCORE_TO_SWITCH = 62.0
MIN_SCORE_TO_TRADE = 48.0
FEE_SAFETY_MARGIN_PCT = 0.03

# Strategy defaults by regime. These are starting priors, not permanent choices.
REGIME_PRIOR_STRATEGIES = {
    "TRENDING_BULL": ["trend_follow", "breakout", "ensemble"],
    "TRENDING_BEAR": ["trend_follow", "breakout", "ensemble"],
    "RANGING": ["mean_revert", "ensemble"],
    "VOLATILE": ["breakout", "ensemble", "trend_follow"],
    "QUIET": ["mean_revert", "ensemble"],
}


@dataclass
class StrategyScore:
    strategy: str
    score: float
    total_samples: int
    win_rate: float
    avg_pnl_pct: float
    profit_factor: float
    source: str
    reason: str


def _available_builtin_strategies() -> List[str]:
    return list(STRATEGIES.keys())


def _unique(seq: Iterable[str]) -> List[str]:
    out: List[str] = []
    for x in seq:
        if x and x not in out:
            out.append(x)
    return out


def _candidate_strategies(configured_strategy: str, regime: str) -> List[str]:
    builtins = _available_builtin_strategies()
    priors = REGIME_PRIOR_STRATEGIES.get(regime, [])
    candidates = _unique([configured_strategy, *priors, "ensemble", *builtins])
    return [s for s in candidates if s in STRATEGIES]


def _score_from_metrics(total: int, win_rate: float, avg_pnl_pct: float, profit_factor: float) -> float:
    """Convert performance metrics to a 0-100 selector score."""
    sample_bonus = min(total, 50) / 50 * 10
    win_component = max(0.0, min(win_rate, 100.0)) * 0.45
    pnl_component = max(-20.0, min(avg_pnl_pct * 100, 30.0))
    pf_component = max(0.0, min((profit_factor - 1.0) * 20.0, 20.0))
    return round(max(0.0, min(100.0, win_component + pnl_component + pf_component + sample_bonus)), 2)


async def _signal_stat_score(user_id: str, strategy: str, ticker: str, timeframe: str, regime: str) -> Optional[StrategyScore]:
    """Score from resolved signal_stats for the exact context."""
    doc = await col_signal_stats.find_one({
        "user_id": user_id,
        "strategy": strategy,
        "ticker": ticker.upper(),
        "timeframe": timeframe,
        "regime": regime,
    })
    if not doc:
        return None

    total = int(doc.get("total", 0) or 0)
    if total < MIN_SIGNAL_SAMPLES:
        return None

    wins = int(doc.get("wins", 0) or 0)
    losses = int(doc.get("losses", 0) or 0)
    pnl_sum = float(doc.get("pnl_sum", 0) or 0)
    win_rate = wins / total * 100 if total else 0.0
    avg_pnl_pct = pnl_sum / total if total else 0.0

    # signal_stats does not store gross wins/losses, so use a conservative PF proxy.
    if losses <= 0 and wins > 0:
        profit_factor = 3.0
    elif losses > 0:
        profit_factor = max(0.1, wins / losses)
    else:
        profit_factor = 1.0

    score = _score_from_metrics(total, win_rate, avg_pnl_pct, profit_factor)
    return StrategyScore(
        strategy=strategy,
        score=score,
        total_samples=total,
        win_rate=round(win_rate, 2),
        avg_pnl_pct=round(avg_pnl_pct, 4),
        profit_factor=round(profit_factor, 3),
        source="signal_stats",
        reason=f"{total} resolved signals, {win_rate:.1f}% WR, avg PnL {avg_pnl_pct:.3f}%",
    )


async def _paper_trade_score(user_id: str, strategy: str, ticker: str, timeframe: str, regime: str) -> Optional[StrategyScore]:
    """Score from paper trades when strategy/timeframe/regime metadata exists."""
    match = {
        "user_id": user_id,
        "broker": "paper",
        "status": "closed",
        "ticker": ticker.upper(),
        "strategy": strategy,
        "timeframe": timeframe,
        "regime": regime,
    }
    docs = await col_trades.find(match).sort("closed_at", -1).limit(100).to_list(100)
    total = len(docs)
    if total < MIN_TRADE_SAMPLES:
        return None

    wins = [float(d.get("pnl_pct", 0) or 0) for d in docs if float(d.get("pnl", 0) or 0) > 0]
    losses = [abs(float(d.get("pnl_pct", 0) or 0)) for d in docs if float(d.get("pnl", 0) or 0) < 0]
    pnl_values = [float(d.get("pnl_pct", 0) or 0) for d in docs]
    win_rate = len(wins) / total * 100 if total else 0.0
    avg_pnl_pct = sum(pnl_values) / total if total else 0.0
    gross_win = sum(wins)
    gross_loss = sum(losses)
    profit_factor = gross_win / gross_loss if gross_loss > 0 else (3.0 if gross_win > 0 else 1.0)

    score = _score_from_metrics(total, win_rate, avg_pnl_pct, profit_factor)
    return StrategyScore(
        strategy=strategy,
        score=score,
        total_samples=total,
        win_rate=round(win_rate, 2),
        avg_pnl_pct=round(avg_pnl_pct, 4),
        profit_factor=round(profit_factor, 3),
        source="paper_trades",
        reason=f"{total} paper trades, {win_rate:.1f}% WR, PF {profit_factor:.2f}, avg PnL {avg_pnl_pct:.3f}%",
    )


def _prior_score(strategy: str, configured_strategy: str, regime: str) -> StrategyScore:
    priors = REGIME_PRIOR_STRATEGIES.get(regime, [])
    if strategy == configured_strategy:
        base = 56.0
        reason = "configured strategy kept as prior because there is not enough learned evidence"
    elif strategy in priors:
        base = 53.0
        reason = f"regime prior for {regime}"
    else:
        base = 48.0
        reason = "neutral strategy prior"
    return StrategyScore(strategy, base, 0, 0.0, 0.0, 1.0, "prior", reason)


async def score_strategy(user_id: str, strategy: str, ticker: str, timeframe: str, regime: str,
                         configured_strategy: str) -> StrategyScore:
    paper = await _paper_trade_score(user_id, strategy, ticker, timeframe, regime)
    signal = await _signal_stat_score(user_id, strategy, ticker, timeframe, regime)

    if paper and signal:
        # Paper trades are closer to execution reality, so weight them more.
        combined_score = round(paper.score * 0.65 + signal.score * 0.35, 2)
        total = paper.total_samples + signal.total_samples
        return StrategyScore(
            strategy=strategy,
            score=combined_score,
            total_samples=total,
            win_rate=round((paper.win_rate + signal.win_rate) / 2, 2),
            avg_pnl_pct=round((paper.avg_pnl_pct + signal.avg_pnl_pct) / 2, 4),
            profit_factor=round((paper.profit_factor + signal.profit_factor) / 2, 3),
            source="paper_trades+signal_stats",
            reason=f"combined paper + signal evidence: {paper.reason}; {signal.reason}",
        )
    if paper:
        return paper
    if signal:
        return signal
    return _prior_score(strategy, configured_strategy, regime)


async def select_strategy(
    user_id: str,
    configured_strategy: str,
    ticker: str,
    timeframe: str,
    regime: str = "unknown",
    allow_auto_switch: bool = True,
    allow_no_trade: bool = True,
) -> Dict[str, Any]:
    """Return the best strategy decision for this ticker/timeframe/regime context."""
    if configured_strategy not in STRATEGIES:
        return {
            "allow_trade": True,
            "selected_strategy": configured_strategy,
            "configured_strategy": configured_strategy,
            "regime": regime,
            "timeframe": timeframe,
            "score": 50.0,
            "reason": "custom/user strategy: selector does not auto-switch custom strategies yet",
            "scores": [],
        }

    candidates = _candidate_strategies(configured_strategy, regime)
    scores = [
        await score_strategy(user_id, s, ticker, timeframe, regime, configured_strategy)
        for s in candidates
    ]
    scores.sort(key=lambda x: x.score, reverse=True)
    best = scores[0] if scores else _prior_score(configured_strategy, configured_strategy, regime)

    selected = configured_strategy
    action = "keep_configured"
    allow_trade = True
    reason = best.reason

    configured_score = next((s for s in scores if s.strategy == configured_strategy), None)
    configured_value = configured_score.score if configured_score else 0.0

    if allow_auto_switch and best.strategy != configured_strategy:
        # Switch only when evidence is materially better, to avoid thrashing.
        if best.score >= MIN_SCORE_TO_SWITCH and best.score >= configured_value + 8:
            selected = best.strategy
            action = "auto_switch"
            reason = f"selected {best.strategy}: {best.reason}"

    # If learned evidence says the context is poor, skip instead of forcing a trade.
    if allow_no_trade and best.total_samples > 0 and best.score < MIN_SCORE_TO_TRADE:
        allow_trade = False
        action = "no_trade"
        reason = f"no positive edge for {ticker.upper()} {timeframe} {regime}: best score {best.score}"

    decision = {
        "allow_trade": allow_trade,
        "selected_strategy": selected,
        "configured_strategy": configured_strategy,
        "regime": regime,
        "timeframe": timeframe,
        "ticker": ticker.upper(),
        "score": best.score if selected == best.strategy else configured_value,
        "best_strategy": best.strategy,
        "action": action,
        "reason": reason,
        "scores": [s.__dict__ for s in scores[:8]],
    }

    try:
        await col_selector_decisions.insert_one({**decision, "user_id": user_id})
    except Exception as e:
        log.debug(f"selector decision logging failed: {e}")

    return decision
