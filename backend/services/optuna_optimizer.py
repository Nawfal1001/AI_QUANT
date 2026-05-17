"""Optuna optimizer for backtesting parameters."""
import asyncio
from functools import partial
import optuna
from services.backtest_engine import run_backtest


def _score(result: dict, objective: str = "balanced") -> float:
    if not result or "error" in result:
        return -1e9
    ret = float(result.get("total_return_pct") or 0)
    sharpe = float(result.get("sharpe") or 0)
    pf = float(result.get("profit_factor") or 0)
    dd = abs(float(result.get("max_drawdown") or 0))
    trades = int(result.get("total_trades") or 0)
    if trades <= 0:
        return -1e6 + ret
    if objective == "return": return ret
    if objective == "sharpe": return sharpe
    if objective == "profit_factor": return pf
    if objective == "return_drawdown": return ret / max(dd, 1)
    return (ret * 0.45) + (sharpe * 12) + (pf * 4) - (dd * 0.8) + min(trades, 50) * 0.15


async def optimize_backtest(req: dict, user: dict, log_fn=None, progress_fn=None):
    ticker = (req.get("ticker") or "AAPL").upper()
    asset_type = req.get("asset_type", "stock")
    days = int(req.get("days", 365))
    capital = float(req.get("capital", 10000))
    strategy = req.get("strategy", "ensemble")
    n_trials = max(5, min(int(req.get("optuna_trials", req.get("trials", 25))), 200))
    objective_name = req.get("objective", "balanced")
    intervals = req.get("intervals") or req.get("timeframes") or [req.get("interval", "1d")]
    if isinstance(intervals, str): intervals = [x.strip() for x in intervals.split(",") if x.strip()]
    intervals = intervals or ["1d"]
    from datetime import datetime, timedelta
    end = datetime.now().strftime("%Y-%m-%d")
    start = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    trials_out = []

    async def run_trial(params):
        return await run_backtest(
            ticker=ticker, asset_type=asset_type, start_date=start, end_date=end, interval=params["interval"],
            initial_capital=capital, risk_per_trade=params["risk_per_trade"], min_confidence=params["min_confidence"],
            sl_atr_mult=params["sl_atr_mult"], tp_atr_mult=params["tp_atr_mult"], fee_bps=float(req.get("fee_bps", 5)),
            slippage_bps=float(req.get("slippage_bps", 3)), spread_bps=float(req.get("spread_bps", 2)),
            max_hold_bars=params["max_hold_bars"], strategy=strategy,
        )

    def suggest(trial):
        return {
            "interval": trial.suggest_categorical("interval", intervals),
            "min_confidence": trial.suggest_int("min_confidence", 35, 85),
            "risk_per_trade": trial.suggest_float("risk_per_trade", 0.005, 0.05),
            "sl_atr_mult": trial.suggest_float("sl_atr_mult", 1.0, 5.0),
            "tp_atr_mult": trial.suggest_float("tp_atr_mult", 1.2, 8.0),
            "max_hold_bars": trial.suggest_int("max_hold_bars", 5, 100),
        }

    async def objective_async(trial):
        params = suggest(trial)
        if log_fn: await log_fn(f"Optuna trial {trial.number + 1}/{n_trials}: {params}")
        result = await run_trial(params)
        score = _score(result, objective_name)
        row = {"number": trial.number, "score": round(score, 4), "params": params, "return": result.get("total_return_pct") if result else None, "sharpe": result.get("sharpe") if result else None, "drawdown": result.get("max_drawdown") if result else None, "trades": result.get("total_trades") if result else None, "error": result.get("error") if isinstance(result, dict) else None}
        trials_out.append(row)
        if log_fn: await log_fn(f"Trial {trial.number + 1}: score={row['score']} return={row['return']} sharpe={row['sharpe']} trades={row['trades']}", data=row)
        if progress_fn: await progress_fn(10 + int(((trial.number + 1) / n_trials) * 80))
        return score

    loop = asyncio.get_event_loop()
    study = optuna.create_study(direction="maximize", sampler=optuna.samplers.TPESampler(seed=42))
    for _ in range(n_trials):
        trial = study.ask()
        value = await objective_async(trial)
        study.tell(trial, value)
    best_params = study.best_params
    if log_fn: await log_fn(f"Best Optuna params: {best_params} | score={study.best_value}", level="success")
    best_result = await run_trial({
        "interval": best_params["interval"], "min_confidence": best_params["min_confidence"],
        "risk_per_trade": best_params["risk_per_trade"], "sl_atr_mult": best_params["sl_atr_mult"],
        "tp_atr_mult": best_params["tp_atr_mult"], "max_hold_bars": best_params["max_hold_bars"],
    })
    return {"mode": "optuna_optimized", "ticker": ticker, "asset_type": asset_type, "strategy": strategy, "objective": objective_name, "trials": trials_out, "best_params": best_params, "best_score": study.best_value, "best_result": best_result}
