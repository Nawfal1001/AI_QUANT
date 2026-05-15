"""
Custom Strategy Engine — runs user-defined strategies safely.

Security model:
- User strategies are stored as Python expressions, not full programs.
- We parse the AST and reject anything that isn't:
  - arithmetic / comparisons / boolean logic
  - calls to whitelisted helpers (rsi, ema, atr, bb_upper, bb_lower, etc.)
  - access to whitelisted variables (close, open, high, low, volume, prev_close)
- No function definitions, imports, attribute access, subscripting beyond [-1],
  no `eval`, no `exec`, no dunders.
- Each rule produces a boolean. The strategy is a list of rules with weights.

A user strategy looks like:
{
  "name": "My Breakout",
  "description": "Custom 50-day breakout",
  "rules": [
    {"when": "close > max(highs[-50:-1])", "weight": 60, "side": "BUY"},
    {"when": "volume > avg_volume(20) * 1.3", "weight": 20, "side": "BUY"},
    {"when": "close < min(lows[-50:-1])", "weight": 60, "side": "SELL"},
  ],
  "min_confidence": 60,
}

Total weighted score per side determines the signal:
- weight >= 80 → STRONG_BUY/SELL
- weight >= 50 → BUY/SELL
- otherwise   → HOLD
"""
import ast
from typing import Dict, List

import numpy as np

# Indicator helpers — same primitives as the built-in strategies
from services.strategies import _ema, _rsi, _atr


# =============================================================================
# AST whitelist
# =============================================================================

# Operator types allowed in user expressions
_ALLOWED_NODES = {
    ast.Expression, ast.Module, ast.Expr,
    # Literals
    ast.Constant, ast.Num, ast.Str,  # Num/Str for older Pythons
    # Operators
    ast.BoolOp, ast.BinOp, ast.UnaryOp, ast.Compare,
    ast.And, ast.Or, ast.Not,
    ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Mod, ast.FloorDiv, ast.Pow,
    ast.UAdd, ast.USub,
    ast.Lt, ast.LtE, ast.Gt, ast.GtE, ast.Eq, ast.NotEq,
    # Containers (for max(highs[-20:]))
    ast.List, ast.Tuple,
    ast.Subscript, ast.Slice, ast.Index,
    # Names and calls
    ast.Name, ast.Load, ast.Call, ast.keyword,
    # if expression (a if cond else b)
    ast.IfExp,
}

# Functions the user can call in expressions
_SAFE_BUILTINS = {
    "min": min, "max": max, "abs": abs, "sum": sum, "len": len, "round": round,
    "True": True, "False": False, "None": None,
}

# Names the user MAY NOT call or reference, even if syntactically valid.
# Defence in depth — the empty __builtins__ at eval time would block these anyway,
# but we reject up front so users get a clear validation error.
_FORBIDDEN_NAMES = {
    "eval", "exec", "compile", "open", "input",
    "globals", "locals", "vars", "dir", "help",
    "getattr", "setattr", "delattr", "hasattr",
    "__import__", "__build_class__", "__loader__", "__name__",
    "type", "object", "super", "isinstance", "issubclass",
    "breakpoint", "memoryview", "classmethod", "staticmethod", "property",
}


class StrategyError(Exception):
    """Raised when a strategy is invalid or fails to evaluate."""


def _walk_validate(node, path="<root>"):
    """Walk the AST and reject anything not whitelisted."""
    if type(node) not in _ALLOWED_NODES:
        raise StrategyError(f"Disallowed syntax: {type(node).__name__} at {path}")

    # Forbid attribute access entirely (no .__class__ shenanigans)
    if isinstance(node, ast.Attribute):
        raise StrategyError(f"Attribute access not allowed at {path}")

    # Forbid dunder names in any identifier
    if isinstance(node, ast.Name) and node.id.startswith("_"):
        raise StrategyError(f"Names starting with underscore not allowed: {node.id}")

    # Forbid explicitly blocked names — defence in depth on top of empty __builtins__
    if isinstance(node, ast.Name) and node.id in _FORBIDDEN_NAMES:
        raise StrategyError(f"Use of '{node.id}' is not allowed")

    # Only allow calls to identified-by-name functions (no f(g)(x) trickery)
    if isinstance(node, ast.Call):
        if not isinstance(node.func, ast.Name):
            raise StrategyError("Only direct function calls by name are allowed")
        # Subscript slice = only int constants or [-N:] [N:M]
    if isinstance(node, ast.Slice):
        for part in (node.lower, node.upper, node.step):
            if part is None:
                continue
            if isinstance(part, ast.UnaryOp) and isinstance(part.operand, ast.Constant) and isinstance(part.operand.value, int):
                continue
            if isinstance(part, ast.Constant) and isinstance(part.value, (int, type(None))):
                continue
            raise StrategyError("Slice bounds must be integer constants")

    for child in ast.iter_child_nodes(node):
        _walk_validate(child, path + "." + type(child).__name__)


def validate_expression(expr: str) -> dict:
    """
    Parse + validate a single expression. Returns:
      {"ok": True} or {"ok": False, "error": str}
    """
    if not isinstance(expr, str) or not expr.strip():
        return {"ok": False, "error": "Empty expression"}
    if len(expr) > 500:
        return {"ok": False, "error": "Expression too long (max 500 chars)"}
    try:
        tree = ast.parse(expr, mode="eval")
    except SyntaxError as e:
        return {"ok": False, "error": f"Syntax error: {e.msg}"}
    try:
        _walk_validate(tree)
    except StrategyError as e:
        return {"ok": False, "error": str(e)}
    return {"ok": True}


def validate_strategy(strategy: dict) -> dict:
    """Validate the full strategy definition."""
    if not isinstance(strategy, dict):
        return {"ok": False, "error": "Strategy must be a JSON object"}

    name = strategy.get("name", "").strip()
    if not name or len(name) > 60:
        return {"ok": False, "error": "Strategy name required (1-60 chars)"}

    rules = strategy.get("rules", [])
    if not isinstance(rules, list) or not rules:
        return {"ok": False, "error": "At least one rule required"}
    if len(rules) > 20:
        return {"ok": False, "error": "Maximum 20 rules per strategy"}

    for i, rule in enumerate(rules):
        if not isinstance(rule, dict):
            return {"ok": False, "error": f"Rule {i+1} must be an object"}
        if rule.get("side") not in ("BUY", "SELL"):
            return {"ok": False, "error": f"Rule {i+1}: side must be 'BUY' or 'SELL'"}
        try:
            w = float(rule.get("weight", 0))
        except (ValueError, TypeError):
            return {"ok": False, "error": f"Rule {i+1}: weight must be numeric"}
        if w <= 0 or w > 100:
            return {"ok": False, "error": f"Rule {i+1}: weight must be in (0, 100]"}
        v = validate_expression(rule.get("when", ""))
        if not v["ok"]:
            return {"ok": False, "error": f"Rule {i+1}: {v['error']}"}

    try:
        min_conf = int(strategy.get("min_confidence", 50))
    except (ValueError, TypeError):
        return {"ok": False, "error": "min_confidence must be an integer"}
    if not 0 <= min_conf <= 100:
        return {"ok": False, "error": "min_confidence must be in [0, 100]"}

    return {"ok": True}


# =============================================================================
# Evaluation
# =============================================================================

def _build_context(window) -> dict:
    """Build the variable + function namespace exposed to a rule expression."""
    closes = window["close"].values
    highs = window["high"].values
    lows = window["low"].values
    opens = window["open"].values
    volumes = window["volume"].values

    close = float(closes[-1])
    open_ = float(opens[-1])
    high = float(highs[-1])
    low = float(lows[-1])
    volume = float(volumes[-1])
    prev_close = float(closes[-2]) if len(closes) >= 2 else close

    # Bollinger helpers
    bb_mean = float(np.mean(closes[-20:])) if len(closes) >= 20 else close
    bb_std = float(np.std(closes[-20:])) if len(closes) >= 20 else 0
    bb_upper = bb_mean + 2 * bb_std
    bb_lower = bb_mean - 2 * bb_std

    # MACD-ish
    ema12 = _ema(closes[-30:], 12) if len(closes) >= 30 else close
    ema26 = _ema(closes[-50:], 26) if len(closes) >= 50 else close
    macd = ema12 - ema26

    rsi_val = _rsi(closes)
    atr_val = _atr(highs, lows, closes)
    atr_pct = atr_val / close * 100 if close else 0

    # Window arrays — bounded so slicing can't ask for huge data
    closes_list = closes[-200:].tolist()
    highs_list = highs[-200:].tolist()
    lows_list = lows[-200:].tolist()
    opens_list = opens[-200:].tolist()
    volumes_list = volumes[-200:].tolist()

    def ema(period: int) -> float:
        period = max(2, min(int(period), 200))
        return float(_ema(closes[-period * 3:][-period * 3:] if len(closes) >= period * 3 else closes, period))

    def avg_volume(period: int) -> float:
        period = max(2, min(int(period), 200))
        slice_ = volumes[-period:]
        return float(np.mean(slice_)) if len(slice_) else 0

    def avg_price(period: int) -> float:
        period = max(2, min(int(period), 200))
        slice_ = closes[-period:]
        return float(np.mean(slice_)) if len(slice_) else 0

    def std(period: int) -> float:
        period = max(2, min(int(period), 200))
        slice_ = closes[-period:]
        return float(np.std(slice_)) if len(slice_) else 0

    return {
        **_SAFE_BUILTINS,
        # Scalars
        "close": close, "open": open_, "high": high, "low": low,
        "volume": volume, "prev_close": prev_close,
        "rsi": rsi_val, "macd": macd, "ema12": ema12, "ema26": ema26,
        "atr": atr_val, "atr_pct": atr_pct,
        "bb_upper": bb_upper, "bb_lower": bb_lower, "bb_mean": bb_mean,
        # Arrays (for slicing in expressions)
        "closes": closes_list, "highs": highs_list, "lows": lows_list,
        "opens": opens_list, "volumes": volumes_list,
        # Functions
        "ema": ema, "avg_volume": avg_volume, "avg_price": avg_price, "std": std,
    }


def evaluate_rule(expr: str, context: dict) -> bool:
    """Evaluate a single rule expression. Returns True/False."""
    # Compile in restricted mode — but eval() is still doing the real work,
    # so validation must have been done up-front.
    v = validate_expression(expr)
    if not v["ok"]:
        raise StrategyError(v["error"])
    try:
        # eval(...) is safe here because we've AST-checked the expression
        # and the namespace contains only whitelisted callables.
        result = eval(expr, {"__builtins__": {}}, context)  # noqa: S307
    except Exception as e:
        raise StrategyError(f"Eval error: {e}")
    return bool(result)


def run_custom_strategy(strategy: dict, window) -> dict:
    """
    Run a user strategy against a window. Returns the same shape as built-ins:
    {"signal": str, "confidence": int, "atr_pct": float, "strategy": str}
    """
    if len(window) < 30:
        return {"signal": "HOLD", "confidence": 0, "atr_pct": 0, "strategy": strategy.get("name", "custom")}

    context = _build_context(window)
    buy_score = 0.0
    sell_score = 0.0
    rules_fired = []

    for rule in strategy.get("rules", []):
        try:
            fired = evaluate_rule(rule["when"], context)
        except StrategyError:
            fired = False
        if fired:
            rules_fired.append(rule["when"])
            w = float(rule["weight"])
            if rule["side"] == "BUY":
                buy_score += w
            else:
                sell_score += w

    min_conf = int(strategy.get("min_confidence", 50))
    name = strategy.get("name", "custom")
    atr_pct = context["atr_pct"]

    if buy_score >= 80 and buy_score > sell_score:
        return {"signal": "STRONG_BUY", "confidence": min(95, int(buy_score)), "atr_pct": atr_pct, "strategy": name, "rules_fired": rules_fired}
    if buy_score >= 50 and buy_score > sell_score:
        return {"signal": "BUY", "confidence": min(80, int(buy_score)), "atr_pct": atr_pct, "strategy": name, "rules_fired": rules_fired}
    if sell_score >= 80 and sell_score > buy_score:
        return {"signal": "STRONG_SELL", "confidence": min(95, int(sell_score)), "atr_pct": atr_pct, "strategy": name, "rules_fired": rules_fired}
    if sell_score >= 50 and sell_score > buy_score:
        return {"signal": "SELL", "confidence": min(80, int(sell_score)), "atr_pct": atr_pct, "strategy": name, "rules_fired": rules_fired}
    return {"signal": "HOLD", "confidence": int(max(buy_score, sell_score)), "atr_pct": atr_pct, "strategy": name, "rules_fired": rules_fired}


# =============================================================================
# Variable reference — what users can use in expressions
# =============================================================================

REFERENCE = {
    "variables": [
        {"name": "close", "desc": "Latest close price"},
        {"name": "open", "desc": "Latest open price"},
        {"name": "high", "desc": "Latest bar high"},
        {"name": "low", "desc": "Latest bar low"},
        {"name": "volume", "desc": "Latest bar volume"},
        {"name": "prev_close", "desc": "Previous bar close"},
        {"name": "rsi", "desc": "RSI(14), 0-100"},
        {"name": "macd", "desc": "MACD line (EMA12 - EMA26)"},
        {"name": "ema12", "desc": "12-period EMA of close"},
        {"name": "ema26", "desc": "26-period EMA of close"},
        {"name": "atr", "desc": "Average True Range, 14-period"},
        {"name": "atr_pct", "desc": "ATR as % of close"},
        {"name": "bb_upper", "desc": "Bollinger upper band (20, 2σ)"},
        {"name": "bb_lower", "desc": "Bollinger lower band"},
        {"name": "bb_mean", "desc": "Bollinger middle band (SMA20)"},
        {"name": "closes", "desc": "Array of last 200 closes (use closes[-N:] for slices)"},
        {"name": "highs", "desc": "Array of last 200 highs"},
        {"name": "lows", "desc": "Array of last 200 lows"},
        {"name": "opens", "desc": "Array of last 200 opens"},
        {"name": "volumes", "desc": "Array of last 200 volumes"},
    ],
    "functions": [
        {"name": "ema(period)", "desc": "EMA of closes over `period` bars"},
        {"name": "avg_price(period)", "desc": "Simple average of closes over `period` bars"},
        {"name": "avg_volume(period)", "desc": "Average volume over `period` bars"},
        {"name": "std(period)", "desc": "Standard deviation of closes over `period` bars"},
        {"name": "min(x, y, ...)", "desc": "Minimum"},
        {"name": "max(x, y, ...)", "desc": "Maximum"},
        {"name": "abs(x)", "desc": "Absolute value"},
        {"name": "sum(arr)", "desc": "Sum a slice"},
        {"name": "len(arr)", "desc": "Length"},
    ],
    "examples": [
        {"name": "RSI oversold", "when": "rsi < 30", "side": "BUY", "weight": 60},
        {"name": "Below lower Bollinger", "when": "close < bb_lower", "side": "BUY", "weight": 30},
        {"name": "20-day breakout", "when": "close > max(highs[-21:-1])", "side": "BUY", "weight": 60},
        {"name": "Volume spike", "when": "volume > avg_volume(20) * 1.5", "side": "BUY", "weight": 20},
        {"name": "Above EMA50", "when": "close > ema(50)", "side": "BUY", "weight": 30},
        {"name": "RSI overbought", "when": "rsi > 70", "side": "SELL", "weight": 60},
        {"name": "Death cross intraday", "when": "ema12 < ema26 and close < ema26", "side": "SELL", "weight": 50},
    ],
}
