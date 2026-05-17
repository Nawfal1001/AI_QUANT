"""Build compact strategy-generation references for ASI-Evolve.
References are intentionally structured so a remote evolver can generate new strategies
without needing direct repo/database access.
"""
from datetime import datetime
from database import db


async def build_strategy_references(user: dict, ticker: str = None, asset_type: str = None, limit: int = 10):
    uid = user.get("id")
    q = {"user_id": uid}
    if ticker:
        q["ticker"] = ticker.upper()
    if asset_type:
        q["asset_type"] = asset_type
    backtests = await db["backtests"].find(q).sort("saved_at", -1).limit(limit).to_list(limit)
    user_strats = await db["user_strategies"].find({"user_id": uid}).sort("updated_at", -1).limit(limit).to_list(limit)
    refs = {
        "generated_at": datetime.utcnow().isoformat(),
        "user_context": {"user_id": uid},
        "target": {"ticker": ticker, "asset_type": asset_type},
        "strategy_contract": {
            "description": "Generate a safe Python strategy definition compatible with AI_QUANT backtesting. Return JSON only.",
            "required_response_fields": ["name", "description", "parameters", "entry_rules", "exit_rules", "risk_rules", "code"],
            "constraints": [
                "No network calls, filesystem writes, subprocess, shell, eval, exec, imports outside approved indicator/math libraries.",
                "Strategy must be deterministic and use only provided OHLCV dataframe columns and indicators.",
                "Include parameter defaults and allowed ranges so Optuna can optimize them later.",
                "Prefer robust risk management: stop loss, take profit, max hold bars, volatility filter."
            ],
            "available_columns": ["date", "open", "high", "low", "close", "volume"],
            "preferred_indicators": ["ema", "rsi", "macd", "atr", "adx", "bollinger", "volume_ratio", "momentum", "volatility"],
        },
        "recent_backtests": [],
        "existing_user_strategies": [],
    }
    for b in backtests:
        refs["recent_backtests"].append({
            "ticker": b.get("ticker"), "asset_type": b.get("asset_type"), "strategy": b.get("strategy"),
            "interval": b.get("interval"), "return_pct": b.get("total_return_pct"), "sharpe": b.get("sharpe"),
            "max_drawdown": b.get("max_drawdown"), "win_rate": b.get("win_rate"), "trades": b.get("trades_count") or b.get("total_trades"),
            "saved_at": b.get("saved_at"),
        })
    for s in user_strats:
        refs["existing_user_strategies"].append({
            "id": str(s.get("_id")), "name": s.get("name"), "description": s.get("description"),
            "parameters": s.get("parameters"), "rules": s.get("rules"), "created_at": s.get("created_at"), "updated_at": s.get("updated_at"),
        })
    return refs
