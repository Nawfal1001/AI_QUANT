"""Paper broker tests."""
import pytest


async def _setup_risk(uid):
    """Quick helper — give the user permissive risk limits so we can test paper trading."""
    from services import risk_engine
    await risk_engine.set_limits(uid, {
        "daily_loss_limit_pct": 99,
        "max_drawdown_pct": 99,
        "max_open_trades": 99,
        "max_position_size_pct": 99,
    })


@pytest.mark.asyncio
async def test_paper_account_created(patch_db):
    from services import paper_broker
    acct = await paper_broker.get_account("u_pa1")
    assert acct["starting_capital"] == 10000
    assert acct["cash"] == 10000


@pytest.mark.asyncio
async def test_paper_buy_fill(patch_db):
    from services import paper_broker
    uid = "u_buy"
    await paper_broker.reset_account(uid, 10000)
    await _setup_risk(uid)

    res = await paper_broker.place_order(
        user_id=uid, ticker="AAPL", side="buy", qty=10,
        order_type="market", current_price=150.0,
        skip_freshness=True,
    )
    assert res["status"] == "filled"
    assert res["order"]["fill_price"] > 150.0  # cost adjustment
    acct = await paper_broker.get_account(uid)
    assert acct["cash"] < 10000


@pytest.mark.asyncio
async def test_paper_sell_realizes_pnl(patch_db):
    from services import paper_broker
    uid = "u_sell"
    await paper_broker.reset_account(uid, 10000)
    await _setup_risk(uid)

    await paper_broker.place_order(uid, "AAPL", "buy", 10, "market", current_price=100, skip_freshness=True)
    # Sell at higher price → realized profit
    res = await paper_broker.place_order(uid, "AAPL", "sell", 10, "market", current_price=120, skip_freshness=True)
    assert res["status"] == "filled"
    assert res["order"]["realized_pnl"] > 0


@pytest.mark.asyncio
async def test_paper_sell_can_open_short(patch_db):
    """Selling more than the held long quantity closes the long and opens a short
    for the remainder. This lets SELL signals from bot_runner enter trades on
    instruments the user doesn't already hold."""
    from services import paper_broker
    uid = "u_short"
    await paper_broker.reset_account(uid, 10000)
    await _setup_risk(uid)

    await paper_broker.place_order(uid, "AAPL", "buy", 5, "market", current_price=100, skip_freshness=True)
    # 5 long → after selling 7, position is -2 (short). Unique (qty=7) avoids idempotency.
    res = await paper_broker.place_order(uid, "AAPL", "sell", 7, "market", current_price=100, skip_freshness=True)
    assert res["status"] == "filled"
    positions = await paper_broker.get_positions(uid, live_prices={"AAPL": 100})
    short = next(p for p in positions["positions"] if p["ticker"] == "AAPL")
    assert short["qty"] < 0
    assert short["side"] == "short"


@pytest.mark.asyncio
async def test_paper_insufficient_cash(patch_db):
    from services import paper_broker
    uid = "u_broke"
    await paper_broker.reset_account(uid, 100)
    await _setup_risk(uid)

    res = await paper_broker.place_order(uid, "AAPL", "buy", 10, "market", current_price=1000, skip_freshness=True)
    assert res["status"] == "rejected"


@pytest.mark.asyncio
async def test_summary_tracks_realized_unrealized(patch_db):
    from services import paper_broker
    uid = "u_summary"
    await paper_broker.reset_account(uid, 10000)
    await _setup_risk(uid)

    # Open and partially close
    await paper_broker.place_order(uid, "AAPL", "buy", 20, "market", current_price=100, skip_freshness=True)
    await paper_broker.place_order(uid, "AAPL", "sell", 10, "market", current_price=110, skip_freshness=True)

    summary = await paper_broker.get_summary(uid, live_prices={"AAPL": 110})
    assert summary["realized_pnl"] > 0
    assert summary["open_positions"] == 1


@pytest.mark.asyncio
async def test_idempotency_blocks_duplicate(patch_db):
    from services import paper_broker
    uid = "u_dup"
    await paper_broker.reset_account(uid, 10000)
    await _setup_risk(uid)

    r1 = await paper_broker.place_order(uid, "AAPL", "buy", 1, "market", current_price=100, skip_freshness=True)
    r2 = await paper_broker.place_order(uid, "AAPL", "buy", 1, "market", current_price=100, skip_freshness=True)
    assert r1["status"] == "filled"
    assert r2["status"] == "rejected"
    assert "duplicate" in r2["reason"].lower()
