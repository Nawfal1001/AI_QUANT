"""Bot CRUD + validation + runner tests."""
import pytest


VALID_BOT = {
    "name": "Test Bot",
    "description": "Test description",
    "strategy_type": "builtin",
    "strategy_id": "ensemble",
    "watchlist": [{"ticker": "AAPL", "asset_type": "stock"}],
    "schedule": "1h",
    "broker": "paper",
    "sizing_mode": "fixed_pct",
    "sizing_pct": 2.0,
    "min_confidence": 60,
    "enabled": False,
}


async def _setup_risk(uid):
    """Helper — set permissive risk limits."""
    from services import risk_engine
    await risk_engine.set_limits(uid, {
        "daily_loss_limit_pct": 99,
        "max_drawdown_pct": 99,
        "max_open_trades": 99,
        "max_position_size_pct": 99,
    })


# ============================================================
# CRUD
# ============================================================

@pytest.mark.asyncio
async def test_create_bot_basic(patch_db):
    from services import bots
    res = await bots.create_bot("u_create", VALID_BOT)
    assert "error" not in res
    assert res["name"] == "Test Bot"
    assert res["enabled"] is False
    assert res["stats"]["runs"] == 0


@pytest.mark.asyncio
async def test_create_bot_validates_name(patch_db):
    from services import bots
    bad = {**VALID_BOT, "name": ""}
    res = await bots.create_bot("u_x", bad)
    assert "error" in res
    assert "name" in res["error"].lower()


@pytest.mark.asyncio
async def test_create_bot_validates_strategy_type(patch_db):
    from services import bots
    bad = {**VALID_BOT, "strategy_type": "invalid"}
    res = await bots.create_bot("u_x", bad)
    assert "error" in res


@pytest.mark.asyncio
async def test_create_bot_validates_watchlist(patch_db):
    from services import bots
    bad = {**VALID_BOT, "watchlist": []}
    res = await bots.create_bot("u_x", bad)
    assert "error" in res
    assert "watchlist" in res["error"].lower()


@pytest.mark.asyncio
async def test_create_bot_rejects_unknown_user_strategy(patch_db):
    """If strategy_type=user but the strategy doesn't exist, create fails."""
    from services import bots
    res = await bots.create_bot("u_xx", {
        **VALID_BOT,
        "strategy_type": "user",
        "strategy_id": "507f1f77bcf86cd799439011",  # fake ObjectId
    })
    assert "error" in res


@pytest.mark.asyncio
async def test_enable_requires_risk_limits(patch_db):
    """Can't create an ENABLED bot without risk limits."""
    from services import bots
    from database import db
    await db["risk_limits"].delete_many({"user_id": "u_rl"})

    res = await bots.create_bot("u_rl", {**VALID_BOT, "enabled": True})
    assert "error" in res
    assert "risk limits" in res["error"].lower()


@pytest.mark.asyncio
async def test_toggle_enabled_requires_risk_limits(patch_db):
    """Toggling an existing bot to enabled also requires risk limits."""
    from services import bots
    from database import db
    await db["risk_limits"].delete_many({"user_id": "u_t"})

    created = await bots.create_bot("u_t", VALID_BOT)
    bot_id = created["_id"]

    res = await bots.toggle_bot("u_t", bot_id, True)
    assert "error" in res
    assert "risk limits" in res["error"].lower()


@pytest.mark.asyncio
async def test_toggle_enabled_works_after_risk_set(patch_db):
    from services import bots
    uid = "u_ok"
    created = await bots.create_bot(uid, VALID_BOT)
    bot_id = created["_id"]
    await _setup_risk(uid)
    res = await bots.toggle_bot(uid, bot_id, True)
    assert "error" not in res
    assert res["enabled"] is True


@pytest.mark.asyncio
async def test_update_and_delete_bot(patch_db):
    from services import bots
    uid = "u_ud"
    created = await bots.create_bot(uid, VALID_BOT)
    bot_id = created["_id"]

    updated = await bots.update_bot(uid, bot_id, {"name": "Renamed", "min_confidence": 75})
    assert updated["name"] == "Renamed"
    assert updated["min_confidence"] == 75

    deleted = await bots.delete_bot(uid, bot_id)
    assert deleted["deleted"] == 1

    assert await bots.get_bot(uid, bot_id) is None


@pytest.mark.asyncio
async def test_user_isolation(patch_db):
    """User A's bot is not visible to user B."""
    from services import bots
    created = await bots.create_bot("u_a", VALID_BOT)
    other = await bots.get_bot("u_b", created["_id"])
    assert other is None


@pytest.mark.asyncio
async def test_sizing_pct_bounds(patch_db):
    from services import bots
    res = await bots.create_bot("u_s", {**VALID_BOT, "sizing_pct": 75})
    assert "error" in res
    res = await bots.create_bot("u_s", {**VALID_BOT, "sizing_pct": 0})
    assert "error" in res


@pytest.mark.asyncio
async def test_schedule_validation(patch_db):
    from services import bots
    res = await bots.create_bot("u_sc", {**VALID_BOT, "schedule": "30s"})
    assert "error" in res


# ============================================================
# Runner — uses real services but mocks the fetch + order
# ============================================================

@pytest.mark.asyncio
async def test_runner_skips_disabled_bots(patch_db, monkeypatch):
    """Disabled bots should never be picked up by get_active_bots."""
    from services import bots
    await bots.create_bot("u_disabled", VALID_BOT)  # enabled=False
    active = await bots.get_active_bots()
    assert all(b["enabled"] for b in active)


@pytest.mark.asyncio
async def test_runner_executes_active_bot(patch_db, monkeypatch):
    """An enabled bot whose schedule has elapsed gets processed."""
    from services import bots, bot_runner
    import pandas as pd
    import numpy as np

    uid = "u_run"
    await _setup_risk(uid)
    created = await bots.create_bot(uid, {**VALID_BOT, "enabled": True})
    bot_id = created["_id"]

    # Mock fetch_history to return synthetic data with a buy signal pattern
    np.random.seed(0)
    n = 60
    closes = 100 + np.cumsum(np.random.normal(0.3, 1.0, n))  # uptrend
    df = pd.DataFrame({
        "date": pd.date_range("2024-01-01", periods=n, freq="D"),
        "open": closes + np.random.normal(0, 0.5, n),
        "high": closes + 1.0,
        "low": closes - 1.0,
        "close": closes,
        "volume": np.random.randint(1_000_000, 5_000_000, n),
    })

    async def fake_fetch(*a, **kw):
        return df

    monkeypatch.setattr(bot_runner, "fetch_history", fake_fetch)

    # Run one cycle
    bot = await bots.get_bot(uid, bot_id)
    await bot_runner._process_bot(bot)

    # Verify execution recorded
    execs = await bots.get_executions(uid, bot_id)
    assert len(execs) >= 1

    # Verify bot bookkeeping updated
    updated = await bots.get_bot(uid, bot_id)
    assert updated["last_run_at"] is not None
    assert updated["next_run_at"] is not None
    assert updated["stats"]["runs"] == 1


@pytest.mark.asyncio
async def test_runner_skips_low_confidence(patch_db, monkeypatch):
    """Below-min-confidence signals get skipped."""
    from services import bots, bot_runner
    import pandas as pd
    import numpy as np

    uid = "u_lowconf"
    await _setup_risk(uid)
    created = await bots.create_bot(uid, {**VALID_BOT, "enabled": True, "min_confidence": 99})
    bot_id = created["_id"]

    np.random.seed(1)
    n = 60
    closes = 100 + np.random.normal(0, 0.5, n)  # flat, low-confidence
    df = pd.DataFrame({
        "date": pd.date_range("2024-01-01", periods=n, freq="D"),
        "open": closes, "high": closes + 0.5, "low": closes - 0.5,
        "close": closes, "volume": np.full(n, 1_000_000),
    })
    async def fake_fetch(*a, **kw):
        return df
    monkeypatch.setattr(bot_runner, "fetch_history", fake_fetch)

    bot = await bots.get_bot(uid, bot_id)
    await bot_runner._process_bot(bot)

    execs = await bots.get_executions(uid, bot_id)
    # Every execution should be "skipped" because min_confidence is unattainable
    assert all(e["action"] == "skipped" for e in execs)


@pytest.mark.asyncio
async def test_runner_respects_kill_switch(patch_db, monkeypatch):
    """Even an enabled bot with valid signals gets blocked when kill switch is on."""
    from services import bots, bot_runner, risk_engine
    import pandas as pd
    import numpy as np

    uid = "u_kill"
    await _setup_risk(uid)
    await risk_engine.set_kill_switch(uid, True)

    created = await bots.create_bot(uid, {**VALID_BOT, "enabled": True, "min_confidence": 0})
    bot_id = created["_id"]

    np.random.seed(2)
    n = 60
    closes = 100 + np.cumsum(np.random.normal(0.5, 0.3, n))
    df = pd.DataFrame({
        "date": pd.date_range("2024-01-01", periods=n, freq="D"),
        "open": closes, "high": closes + 1, "low": closes - 1,
        "close": closes, "volume": np.full(n, 2_000_000),
    })
    async def fake_fetch(*a, **kw):
        return df
    monkeypatch.setattr(bot_runner, "fetch_history", fake_fetch)

    bot = await bots.get_bot(uid, bot_id)
    await bot_runner._process_bot(bot)

    execs = await bots.get_executions(uid, bot_id)
    # Any attempts to place orders should have been rejected
    placed = [e for e in execs if e["action"] == "placed"]
    assert len(placed) == 0
