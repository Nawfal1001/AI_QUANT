"""
Tests for the custom-strategy sandbox.
Critical: verify that malicious expressions are rejected before they can run.
"""
import numpy as np
import pandas as pd
import pytest


def _make_window(n=60):
    np.random.seed(42)
    closes = 100 * np.cumprod(1 + np.random.normal(0.001, 0.02, n))
    return pd.DataFrame({
        "date": pd.date_range("2024-01-01", periods=n, freq="D"),
        "open": closes * (1 + np.random.normal(0, 0.003, n)),
        "high": closes * (1 + np.abs(np.random.normal(0, 0.005, n))),
        "low": closes * (1 - np.abs(np.random.normal(0, 0.005, n))),
        "close": closes,
        "volume": np.random.randint(1_000_000, 5_000_000, n),
    })


# ============================================================
# Security — these MUST be rejected
# ============================================================

DANGEROUS_EXPRESSIONS = [
    "__import__('os').system('whoami')",       # builtins
    "().__class__.__bases__[0]",               # class navigation
    "open('/etc/passwd').read()",              # file IO
    "exec('import os; os.system(\"ls\")')",    # exec
    "eval('1+1')",                              # nested eval
    "lambda x: x",                              # lambdas not allowed
    "[x for x in range(10)]",                  # comprehensions
    "globals()",                                # globals
    "locals()",                                 # locals
    "rsi.__class__",                            # attribute access
    "object.__subclasses__()",                  # subclass introspection
    "close = 999",                              # assignment
    "import os",                                # imports
    "f'{rsi}'",                                 # f-strings (technically harmless but unsupported)
]


@pytest.mark.parametrize("expr", DANGEROUS_EXPRESSIONS)
def test_dangerous_expressions_rejected(expr):
    from services.custom_strategy import validate_expression
    v = validate_expression(expr)
    assert v["ok"] is False, f"Should have rejected: {expr}"


def test_eval_in_strategy_rule_rejected():
    """If validation is bypassed somehow, eval_rule itself should also refuse."""
    from services.custom_strategy import evaluate_rule, StrategyError
    with pytest.raises(StrategyError):
        evaluate_rule("__import__('os')", {"close": 100})


def test_underscored_name_rejected():
    from services.custom_strategy import validate_expression
    assert validate_expression("_close > 0")["ok"] is False
    assert validate_expression("__class__")["ok"] is False


def test_attribute_access_rejected():
    from services.custom_strategy import validate_expression
    assert validate_expression("rsi.real")["ok"] is False


def test_too_long_expression_rejected():
    from services.custom_strategy import validate_expression
    expr = "close" + " + 1" * 200
    assert validate_expression(expr)["ok"] is False


# ============================================================
# Functionality — these MUST be accepted and produce correct results
# ============================================================

SAFE_EXPRESSIONS = [
    "rsi < 30",
    "close > bb_upper",
    "close > max(highs[-21:-1])",
    "volume > avg_volume(20) * 1.3",
    "ema12 > ema26 and close > ema26",
    "abs(close - prev_close) / prev_close > 0.02",
    "close > ema(50) and rsi > 50",
    "macd > 0 if close > bb_mean else macd < 0",
    "(close - bb_lower) / (bb_upper - bb_lower) < 0.2",
]


@pytest.mark.parametrize("expr", SAFE_EXPRESSIONS)
def test_safe_expressions_accepted(expr):
    from services.custom_strategy import validate_expression
    v = validate_expression(expr)
    assert v["ok"], f"Should have accepted: {expr}, got: {v.get('error')}"


def test_evaluate_simple_rule():
    from services.custom_strategy import evaluate_rule
    window = _make_window()
    from services.custom_strategy import _build_context
    ctx = _build_context(window)
    assert evaluate_rule("close > 0", ctx) is True
    assert evaluate_rule("close < 0", ctx) is False
    assert evaluate_rule("close > prev_close - 1000", ctx) is True


def test_evaluate_array_slice():
    from services.custom_strategy import evaluate_rule, _build_context
    window = _make_window()
    ctx = _build_context(window)
    # Always true: the latest close is in the recent closes array
    assert evaluate_rule("close <= max(closes[-30:])", ctx) is True


def test_run_custom_strategy_with_no_fires():
    from services.custom_strategy import run_custom_strategy
    strategy = {
        "name": "always_false",
        "rules": [
            {"when": "rsi < 0", "weight": 100, "side": "BUY"},  # impossible
        ],
        "min_confidence": 50,
    }
    result = run_custom_strategy(strategy, _make_window())
    assert result["signal"] == "HOLD"


def test_run_custom_strategy_strong_buy():
    from services.custom_strategy import run_custom_strategy
    strategy = {
        "name": "always_buy",
        "rules": [
            {"when": "close > 0", "weight": 90, "side": "BUY"},
        ],
        "min_confidence": 50,
    }
    result = run_custom_strategy(strategy, _make_window())
    assert result["signal"] == "STRONG_BUY"
    assert result["strategy"] == "always_buy"


# ============================================================
# Validation rules
# ============================================================

def test_validate_strategy_requires_name():
    from services.custom_strategy import validate_strategy
    res = validate_strategy({"rules": [{"when": "rsi < 30", "weight": 50, "side": "BUY"}]})
    assert res["ok"] is False


def test_validate_strategy_requires_rules():
    from services.custom_strategy import validate_strategy
    res = validate_strategy({"name": "x", "rules": []})
    assert res["ok"] is False


def test_validate_strategy_rejects_bad_side():
    from services.custom_strategy import validate_strategy
    res = validate_strategy({
        "name": "x",
        "rules": [{"when": "rsi < 30", "weight": 50, "side": "HOLD"}],
    })
    assert res["ok"] is False


def test_validate_strategy_rejects_bad_weight():
    from services.custom_strategy import validate_strategy
    res = validate_strategy({
        "name": "x",
        "rules": [{"when": "rsi < 30", "weight": 200, "side": "BUY"}],
    })
    assert res["ok"] is False


def test_validate_strategy_rejects_too_many_rules():
    from services.custom_strategy import validate_strategy
    res = validate_strategy({
        "name": "x",
        "rules": [{"when": "rsi < 30", "weight": 1, "side": "BUY"}] * 25,
    })
    assert res["ok"] is False


def test_validate_strategy_propagates_rule_errors():
    from services.custom_strategy import validate_strategy
    res = validate_strategy({
        "name": "x",
        "rules": [{"when": "__import__('os')", "weight": 50, "side": "BUY"}],
    })
    assert res["ok"] is False


# ============================================================
# CRUD service
# ============================================================

@pytest.mark.asyncio
async def test_save_load_delete_strategy(patch_db):
    from services.user_strategies import save_user_strategy, get_user_strategy, list_user_strategies, delete_user_strategy

    uid = "u_strat"
    doc = await save_user_strategy(uid, {
        "name": "My Test",
        "description": "Buy oversold",
        "rules": [{"when": "rsi < 30", "weight": 60, "side": "BUY"}],
        "min_confidence": 50,
    })
    assert "_id" in doc
    sid = doc["_id"]

    loaded = await get_user_strategy(uid, sid)
    assert loaded["name"] == "My Test"

    listed = await list_user_strategies(uid)
    assert any(s["_id"] == sid for s in listed)

    res = await delete_user_strategy(uid, sid)
    assert res["deleted"] == 1

    assert await get_user_strategy(uid, sid) is None


@pytest.mark.asyncio
async def test_user_cannot_load_others_strategies(patch_db):
    from services.user_strategies import save_user_strategy, get_user_strategy

    doc = await save_user_strategy("user_a", {
        "name": "Private",
        "rules": [{"when": "rsi < 30", "weight": 50, "side": "BUY"}],
    })
    other = await get_user_strategy("user_b", doc["_id"])
    assert other is None
