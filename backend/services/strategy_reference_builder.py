"""Build compact strategy-generation references for ASI-Evolve.
References are intentionally structured so a remote evolver can generate new strategies
without needing direct repo/database access.
"""
from datetime import datetime
from database import db

TRADINGVIEW_STYLE_INDICATORS = [
    {"name": "RSI", "category": "momentum", "python_hint": "ta.momentum.RSIIndicator", "params": {"window": [7, 14, 21, 28]}},
    {"name": "Stochastic RSI", "category": "momentum", "python_hint": "ta.momentum.StochRSIIndicator", "params": {"window": [14, 21], "smooth1": [3, 5], "smooth2": [3, 5]}},
    {"name": "MACD", "category": "trend/momentum", "python_hint": "ta.trend.MACD", "params": {"fast": [8, 12, 16], "slow": [21, 26, 34], "signal": [5, 9]}},
    {"name": "EMA", "category": "trend", "python_hint": "pandas ewm", "params": {"window": [9, 20, 50, 100, 200]}},
    {"name": "SMA", "category": "trend", "python_hint": "pandas rolling mean", "params": {"window": [20, 50, 100, 200]}},
    {"name": "Bollinger Bands", "category": "volatility", "python_hint": "ta.volatility.BollingerBands", "params": {"window": [20, 30], "std": [1.5, 2.0, 2.5]}},
    {"name": "ATR", "category": "risk/volatility", "python_hint": "ta.volatility.AverageTrueRange", "params": {"window": [7, 14, 21]}},
    {"name": "ADX", "category": "trend strength", "python_hint": "ta.trend.ADXIndicator", "params": {"window": [14, 21]}},
    {"name": "Supertrend", "category": "trend", "python_hint": "implement from ATR bands", "params": {"atr_window": [10, 14], "multiplier": [2.0, 3.0, 4.0]}},
    {"name": "VWAP", "category": "volume", "python_hint": "cumulative typical_price*volume / cumulative volume", "params": {"session": ["rolling", "daily"]}},
    {"name": "Volume MA / Volume Ratio", "category": "volume", "python_hint": "volume / rolling_volume_mean", "params": {"window": [20, 50]}},
    {"name": "Ichimoku", "category": "trend", "python_hint": "ta.trend.IchimokuIndicator", "params": {"window1": [9], "window2": [26], "window3": [52]}},
]

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
            "description": "Generate a safe Python strategy definition compatible with AI_QUANT backtesting. Return JSON only. TradingView/Pine ideas are allowed as inspiration, but output must be executable Python logic using local OHLCV data.",
            "required_response_fields": ["name", "description", "parameters", "entry_rules", "exit_rules", "risk_rules", "code"],
            "constraints": [
                "Do not scrape TradingView or call TradingView from generated strategy code.",
                "Do not copy proprietary/private Pine scripts. Public indicator concepts are allowed only as inspiration.",
                "No network calls, filesystem writes, subprocess, shell, eval, exec, imports outside approved indicator/math libraries.",
                "Strategy must be deterministic and use only provided OHLCV dataframe columns and locally computed indicators.",
                "Include parameter defaults and allowed ranges so Optuna can optimize them later.",
                "Prefer robust risk management: stop loss, take profit, max hold bars, volatility filter."
            ],
            "available_columns": ["date", "open", "high", "low", "close", "volume"],
            "approved_indicator_libraries": ["ta", "pandas", "numpy"],
            "tradingview_style_indicators": TRADINGVIEW_STYLE_INDICATORS,
            "preferred_indicators": ["ema", "rsi", "macd", "atr", "adx", "supertrend", "vwap", "bollinger", "volume_ratio", "ichimoku", "momentum", "volatility"],
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
