"""
Universal multi-symbol, multi-timeframe backtest harness.

`run_universal_backtest` runs a single parameter set across a list of
symbols x timeframes, aggregates results, and returns a portfolio-level
summary (equal-weighted average of per-leg returns/Sharpes plus a combined
trade log).

`optimize_universal` wraps Optuna around it: each trial picks a `universal`
parameter set and gets a score that mixes return, Sharpe, drawdown and
profit factor across the entire grid — so the optimiser favours parameters
that generalise across symbols and timeframes rather than overfitting to one.
"""
from __future__ import annotations
import asyncio
from datetime import datetime, timedelta
from typing import Iterable, Optional

import optuna

from database import db
from services.backtest_engine import run_backtest
from services.universal_strategy import UNIVERSAL_PARAM_SPACE, DEFAULT_PARAMS, _merge

col_suggestions = db["bot_strategy_suggestions"]
col_universal_runs = db["universal_backtests"]


def _normalize_symbols(symbols):
    out = []
    if not symbols:
        return out
    if isinstance(symbols, str):
        symbols = [s.strip() for s in symbols.split(",") if s.strip()]
    for s in symbols:
        if isinstance(s, dict):
            t = (s.get("ticker") or "").upper().strip()
            if t:
                out.append({"ticker": t, "asset_type": (s.get("asset_type") or "stock").lower()})
        else:
            out.append({"ticker": str(s).upper().strip(), "asset_type": "stock"})
    return out


def _normalize_intervals(intervals):
    if not intervals:
        return ["1d"]
    if isinstance(intervals, str):
        return [x.strip() for x in intervals.split(",") if x.strip()]
    return [str(x).strip() for x in intervals if str(x).strip()]


def _suggest_params(trial, fixed_params: Optional[dict] = None):
    fixed = fixed_params or {}
    params = {}
    for name, spec in UNIVERSAL_PARAM_SPACE.items():
        if name in fixed and fixed[name] is not None:
            params[name] = fixed[name]
            continue
        kind, lo, hi = spec
        if kind == "int":
            params[name] = trial.suggest_int(name, int(lo), int(hi))
        else:
            params[name] = trial.suggest_float(name, float(lo), float(hi))
    # Cross-parameter sanity
    if params.get("ema_fast", 0) >= params.get("ema_slow", 1):
        params["ema_fast"] = max(2, params["ema_slow"] // 2)
    return params


async def _run_leg(symbol, interval, start, end, params, run_kwargs):
    return await run_backtest(
        ticker=symbol["ticker"],
        asset_type=symbol["asset_type"],
        start_date=start,
        end_date=end,
        interval=interval,
        strategy="universal",
        strategy_params=params,
        **run_kwargs,
    )


def _aggregate(legs):
    valid = [r for r in legs if isinstance(r, dict) and "error" not in r]
    failed = [r for r in legs if isinstance(r, dict) and "error" in r]
    if not valid:
        return {
            "valid_legs": 0,
            "failed_legs": len(failed),
            "avg_return_pct": 0.0,
            "avg_sharpe": 0.0,
            "avg_drawdown": 0.0,
            "avg_profit_factor": 0.0,
            "avg_win_rate": 0.0,
            "total_trades": 0,
        }
    n = len(valid)
    avg = lambda k: sum(float(r.get(k, 0) or 0) for r in valid) / n
    total_trades = sum(int(r.get("total_trades", 0) or 0) for r in valid)
    return {
        "valid_legs": n,
        "failed_legs": len(failed),
        "avg_return_pct": round(avg("total_return_pct"), 3),
        "avg_sharpe": round(avg("sharpe"), 3),
        "avg_drawdown": round(avg("max_drawdown"), 3),
        "avg_profit_factor": round(avg("profit_factor"), 3),
        "avg_win_rate": round(avg("win_rate"), 3),
        "total_trades": total_trades,
    }


def _score(agg, objective: str = "balanced") -> float:
    if not agg or agg.get("valid_legs", 0) == 0:
        return -1e9
    ret = agg["avg_return_pct"]
    sharpe = agg["avg_sharpe"]
    pf = agg["avg_profit_factor"]
    dd = abs(agg["avg_drawdown"])
    trades = agg["total_trades"]
    if trades <= 0:
        return -1e6 + ret
    if objective == "return":
        return ret
    if objective == "sharpe":
        return sharpe
    if objective == "profit_factor":
        return pf
    if objective == "return_drawdown":
        return ret / max(dd, 1)
    # Balanced: weight stability across legs.
    consistency = agg["valid_legs"] / max(agg["valid_legs"] + agg["failed_legs"], 1)
    return (ret * 0.4) + (sharpe * 10) + (pf * 4) - (dd * 0.7) + min(trades, 100) * 0.1 + consistency * 8


async def run_universal_backtest(req: dict):
    """Run one parameter set across symbols x timeframes and return aggregate + per-leg results."""
    symbols = _normalize_symbols(req.get("symbols") or req.get("tickers"))
    if not symbols:
        # Fall back to a single symbol so callers can use this for normal backtests too.
        symbols = [{"ticker": (req.get("ticker") or "AAPL").upper(), "asset_type": req.get("asset_type", "stock")}]
    intervals = _normalize_intervals(req.get("intervals") or req.get("timeframes") or req.get("interval"))
    days = int(req.get("days", 365))
    end = datetime.now().strftime("%Y-%m-%d")
    start = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")

    params = _merge(req.get("strategy_params") or req.get("params"))
    max_parallel = max(1, int(req.get("max_parallel", 4)))
    sem = asyncio.Semaphore(max_parallel)
    run_kwargs = dict(
        initial_capital=float(req.get("capital", 10000)),
        risk_per_trade=float(req.get("risk_per_trade", 0.02)),
        min_confidence=int(req.get("min_confidence", 55)),
        sl_atr_mult=float(req.get("sl_atr_mult", 2.0)),
        tp_atr_mult=float(req.get("tp_atr_mult", 3.0)),
        fee_bps=float(req.get("fee_bps", 5)),
        slippage_bps=float(req.get("slippage_bps", 3)),
        spread_bps=float(req.get("spread_bps", 2)),
        max_hold_bars=int(req.get("max_hold_bars", 30)),
    )

    async def _bound(symbol, interval):
        async with sem:
            try:
                r = await _run_leg(symbol, interval, start, end, params, run_kwargs)
            except Exception as e:
                r = {"error": str(e)}
            r["leg"] = {"ticker": symbol["ticker"], "asset_type": symbol["asset_type"], "interval": interval}
            return r

    jobs = [(s, iv) for s in symbols for iv in intervals]
    legs = await asyncio.gather(*[_bound(s, iv) for s, iv in jobs])
    agg = _aggregate(legs)
    summary = [
        {
            "ticker": r["leg"]["ticker"],
            "asset_type": r["leg"]["asset_type"],
            "interval": r["leg"]["interval"],
            "return_pct": r.get("total_return_pct"),
            "sharpe": r.get("sharpe"),
            "drawdown": r.get("max_drawdown"),
            "win_rate": r.get("win_rate"),
            "trades": r.get("total_trades"),
            "error": r.get("error"),
        }
        for r in legs
    ]
    return {
        "mode": "universal_multi",
        "symbols": symbols,
        "intervals": intervals,
        "days": days,
        "params": params,
        "aggregate": agg,
        "summary": summary,
        "legs": legs,
    }


async def optimize_universal(req: dict, user: dict, log_fn=None, progress_fn=None):
    """Optuna optimisation of the universal strategy across symbols x timeframes."""
    symbols = _normalize_symbols(req.get("symbols") or req.get("tickers")) or [{"ticker": (req.get("ticker") or "AAPL").upper(), "asset_type": req.get("asset_type", "stock")}]
    intervals = _normalize_intervals(req.get("intervals") or req.get("timeframes") or req.get("interval"))
    n_trials = max(5, min(int(req.get("optuna_trials", req.get("trials", 25))), 300))
    objective_name = req.get("objective", "balanced")
    fixed_params = req.get("fixed_params") or {}

    trials_out = []

    async def evaluate(params):
        return await run_universal_backtest({**req, "symbols": symbols, "intervals": intervals, "strategy_params": params})

    async def objective_async(trial):
        params = _suggest_params(trial, fixed_params=fixed_params)
        if log_fn:
            await log_fn(f"Trial {trial.number+1}/{n_trials}: testing {len(symbols)}x{len(intervals)} legs")
        result = await evaluate(params)
        agg = result.get("aggregate") or {}
        score = _score(agg, objective_name)
        row = {
            "number": trial.number,
            "score": round(score, 4),
            "params": params,
            "aggregate": agg,
        }
        trials_out.append(row)
        if log_fn:
            await log_fn(
                f"Trial {trial.number+1}: score={row['score']} avg_return={agg.get('avg_return_pct')} "
                f"avg_sharpe={agg.get('avg_sharpe')} trades={agg.get('total_trades')}",
                data=row,
            )
        if progress_fn:
            await progress_fn(10 + int(((trial.number + 1) / n_trials) * 80))
        return score

    study = optuna.create_study(direction="maximize", sampler=optuna.samplers.TPESampler(seed=42))
    for _ in range(n_trials):
        trial = study.ask()
        value = await objective_async(trial)
        study.tell(trial, value)

    best_params = {**DEFAULT_PARAMS, **study.best_params}
    best_result = await evaluate(best_params)

    suggestion = None
    try:
        doc = {
            "user_id": str(user.get("id") or user.get("_id") or user.get("email") or "global") if isinstance(user, dict) else "global",
            "source": "optuna_universal",
            "status": "suggested",
            "strategy": "universal",
            "strategy_mode": "universal_multi",
            "objective": objective_name,
            "symbols": symbols,
            "intervals": intervals,
            "best_params": best_params,
            "best_score": float(study.best_value),
            "aggregate": best_result.get("aggregate"),
            "trials_count": len(trials_out),
            "bot_config_suggestion": {
                "strategy_id": "universal",
                "strategy_params": best_params,
                "symbols": symbols,
                "intervals": intervals,
                "min_confidence": int(req.get("min_confidence", 55)),
                "sizing_mode": "fixed_pct",
                "sizing_pct": float(req.get("risk_per_trade", 0.02)) * 100,
            },
            "created_at": datetime.utcnow().isoformat(),
        }
        res = await col_suggestions.insert_one(doc)
        doc["_id"] = str(res.inserted_id)
        suggestion = doc
    except Exception as e:
        if log_fn:
            await log_fn(f"Could not save universal suggestion: {e}", level="warning")

    try:
        await col_universal_runs.insert_one(
            {
                "user_id": (user or {}).get("id") if isinstance(user, dict) else None,
                "symbols": symbols,
                "intervals": intervals,
                "best_params": best_params,
                "best_score": float(study.best_value),
                "aggregate": best_result.get("aggregate"),
                "trials_count": len(trials_out),
                "objective": objective_name,
                "created_at": datetime.utcnow().isoformat(),
            }
        )
    except Exception:
        pass

    return {
        "mode": "optuna_universal",
        "symbols": symbols,
        "intervals": intervals,
        "objective": objective_name,
        "trials": trials_out,
        "best_params": best_params,
        "best_score": float(study.best_value),
        "best_result": best_result,
        "suggestion": suggestion,
    }
