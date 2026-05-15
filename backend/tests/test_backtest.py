"""Backtest engine tests — uses synthetic data, no network."""
import pytest
import numpy as np
import pandas as pd


def _synthetic_df(n=200, trend=0.001, vol=0.02, seed=42):
    np.random.seed(seed)
    returns = np.random.normal(trend, vol, n)
    closes = 100 * np.cumprod(1 + returns)
    highs = closes * (1 + np.abs(np.random.normal(0, 0.005, n)))
    lows = closes * (1 - np.abs(np.random.normal(0, 0.005, n)))
    opens = closes * (1 + np.random.normal(0, 0.003, n))
    vols = np.random.randint(1_000_000, 5_000_000, n)
    dates = pd.date_range(start="2024-01-01", periods=n, freq="D")
    return pd.DataFrame({"date": dates, "open": opens, "high": highs, "low": lows, "close": closes, "volume": vols})


@pytest.mark.asyncio
async def test_backtest_runs(monkeypatch):
    from services import backtest_engine
    async def fake_fetch(*a, **kw):
        return _synthetic_df()
    monkeypatch.setattr(backtest_engine, "fetch_history", fake_fetch)

    r = await backtest_engine.run_backtest("SYN", "stock", "2024-01-01", "2024-07-01", "1d", 10000, strategy="ensemble")
    assert "error" not in r
    assert r["status"] == "completed"
    assert r["bars"] == 200
    assert "equity_curve" in r
    assert "drawdown_curve" in r
    assert "trades" in r
    assert "sharpe" in r


@pytest.mark.asyncio
async def test_backtest_strategies(monkeypatch):
    from services import backtest_engine
    async def fake_fetch(*a, **kw):
        return _synthetic_df()
    monkeypatch.setattr(backtest_engine, "fetch_history", fake_fetch)

    for strategy in ["trend_follow", "mean_revert", "breakout", "ensemble"]:
        r = await backtest_engine.run_backtest("SYN", "stock", "2024-01-01", "2024-07-01", "1d", 10000, strategy=strategy)
        assert "error" not in r
        assert r["strategy"] == strategy


@pytest.mark.asyncio
async def test_backtest_unknown_strategy(monkeypatch):
    from services import backtest_engine
    async def fake_fetch(*a, **kw):
        return _synthetic_df()
    monkeypatch.setattr(backtest_engine, "fetch_history", fake_fetch)

    r = await backtest_engine.run_backtest("SYN", "stock", "2024-01-01", "2024-07-01", "1d", 10000, strategy="bogus")
    assert "error" in r


@pytest.mark.asyncio
async def test_backtest_insufficient_data(monkeypatch):
    from services import backtest_engine
    async def fake_fetch(*a, **kw):
        return _synthetic_df(n=20)  # too few bars
    monkeypatch.setattr(backtest_engine, "fetch_history", fake_fetch)

    r = await backtest_engine.run_backtest("SYN", "stock", "2024-01-01", "2024-01-20", "1d", 10000)
    assert "error" in r


@pytest.mark.asyncio
async def test_compare_returns_all_strategies(monkeypatch):
    from services import backtest_engine
    async def fake_fetch(*a, **kw):
        return _synthetic_df()
    monkeypatch.setattr(backtest_engine, "fetch_history", fake_fetch)

    r = await backtest_engine.run_compare(
        "SYN", "stock", "2024-01-01", "2024-07-01", "1d", 10000,
        ["trend_follow", "mean_revert", "ensemble"],
    )
    assert "strategies" in r
    assert len(r["strategies"]) == 3
