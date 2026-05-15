"""Risk engine tests."""
import pytest


@pytest.mark.asyncio
async def test_unconfigured_limits_block_orders(patch_db):
    from services import risk_engine
    from database import db
    await db["risk_limits"].delete_many({})
    res = await risk_engine.check_order("user_x", 100, "AAPL")
    assert not res["allowed"]
    assert "not configured" in res["reason"].lower()


@pytest.mark.asyncio
async def test_set_limits_validates_required_fields(patch_db):
    from services import risk_engine
    res = await risk_engine.set_limits("user_y", {"daily_loss_limit_pct": 2.0})
    assert "error" in res


@pytest.mark.asyncio
async def test_set_limits_accepts_complete(patch_db):
    from services import risk_engine
    res = await risk_engine.set_limits("user_z", {
        "daily_loss_limit_pct": 2.0,
        "max_drawdown_pct": 10.0,
        "max_open_trades": 5,
        "max_position_size_pct": 5.0,
    })
    assert res.get("status") == "saved"


@pytest.mark.asyncio
async def test_kill_switch_blocks(patch_db):
    from services import risk_engine
    from database import db
    await db["risk_limits"].delete_many({})
    await risk_engine.set_limits("user_k", {
        "daily_loss_limit_pct": 2.0,
        "max_drawdown_pct": 10.0,
        "max_open_trades": 5,
        "max_position_size_pct": 5.0,
    })
    await risk_engine.set_kill_switch("user_k", True)
    res = await risk_engine.check_order("user_k", 100, "AAPL")
    assert not res["allowed"]
    assert "kill switch" in res["reason"].lower()


@pytest.mark.asyncio
async def test_position_size_limit(patch_db):
    from services import risk_engine
    from database import db
    await db["risk_limits"].delete_many({})
    await db["trades"].delete_many({})
    await db["risk_state"].delete_many({})
    await risk_engine.set_limits("user_p", {
        "daily_loss_limit_pct": 2.0,
        "max_drawdown_pct": 10.0,
        "max_open_trades": 5,
        "max_position_size_pct": 5.0,
    })
    res = await risk_engine.check_order("user_p", 600, "AAPL")
    assert not res["allowed"]
    res = await risk_engine.check_order("user_p", 400, "AAPL")
    assert res["allowed"]
