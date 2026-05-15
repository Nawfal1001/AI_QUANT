"""
Broker adapter tests.

We mock the HTTP/ccxt clients so tests don't hit real broker servers.
"""
from unittest.mock import patch, AsyncMock, MagicMock

import pytest


# ============================================================
# Alpaca
# ============================================================

class _MockResp:
    def __init__(self, status, text):
        self.status = status
        self._text = text

    async def text(self):
        return self._text

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False


class _MockSession:
    def __init__(self, status, text):
        self.status = status
        self._text = text

    def request(self, method, url, headers=None, **kwargs):
        return _MockResp(self.status, self._text)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False


@pytest.mark.asyncio
async def test_alpaca_test_connection_success():
    from services.brokers.alpaca import AlpacaAdapter
    adapter = AlpacaAdapter({"api_key": "k", "api_secret": "s"}, paper_mode=True)

    mock_session = _MockSession(200, '{"cash": "12345.67"}')
    with patch("aiohttp.ClientSession", return_value=mock_session):
        result = await adapter.test_connection()
    assert result["status"] == "connected"
    assert result["balance"] == 12345.67


@pytest.mark.asyncio
async def test_alpaca_test_connection_auth_failed():
    from services.brokers.alpaca import AlpacaAdapter
    adapter = AlpacaAdapter({"api_key": "k", "api_secret": "s"}, paper_mode=True)

    mock_session = _MockSession(401, '{"message": "unauthorized"}')
    with patch("aiohttp.ClientSession", return_value=mock_session):
        result = await adapter.test_connection()
    assert result["status"] == "auth_failed"


@pytest.mark.asyncio
async def test_alpaca_place_order():
    from services.brokers.alpaca import AlpacaAdapter
    adapter = AlpacaAdapter({"api_key": "k", "api_secret": "s"}, paper_mode=True)

    body = '{"id": "order-123", "status": "accepted", "filled_qty": "0"}'
    mock_session = _MockSession(200, body)
    with patch("aiohttp.ClientSession", return_value=mock_session):
        result = await adapter.place_order("AAPL", "buy", 10, "market")
    assert result["broker_order_id"] == "order-123"
    assert result["status"] == "accepted"


# ============================================================
# Binance
# ============================================================

@pytest.mark.asyncio
async def test_binance_test_connection():
    """Binance uses ccxt — we mock the client."""
    with patch("ccxt.binance") as MockBinance:
        instance = MagicMock()
        instance.fetch_balance.return_value = {"USDT": {"free": 5000.0}}
        MockBinance.return_value = instance

        from services.brokers.binance import BinanceAdapter
        adapter = BinanceAdapter({"api_key": "k", "api_secret": "s"}, paper_mode=False)
        result = await adapter.test_connection()
    assert result["status"] == "connected"
    assert result["balance"] == 5000.0


@pytest.mark.asyncio
async def test_binance_paper_blocks_orders():
    """Binance has no paper API — paper mode should reject orders."""
    with patch("ccxt.binance") as MockBinance:
        MockBinance.return_value = MagicMock()
        from services.brokers.binance import BinanceAdapter
        adapter = BinanceAdapter({"api_key": "k", "api_secret": "s"}, paper_mode=True)
        result = await adapter.place_order("BTC", "buy", 0.1, "market")
    assert result["status"] == "rejected"
    assert "paper" in result["message"].lower()


# ============================================================
# Factory + error
# ============================================================

def test_factory_unsupported():
    from services.brokers import make_adapter, BrokerError
    with pytest.raises(BrokerError):
        make_adapter("nonexistent", {})


def test_factory_creates_correct_adapter():
    with patch("ccxt.binance"):
        from services.brokers import make_adapter
        from services.brokers.alpaca import AlpacaAdapter
        from services.brokers.binance import BinanceAdapter

        a = make_adapter("alpaca", {"api_key": "k", "api_secret": "s"})
        b = make_adapter("binance", {"api_key": "k", "api_secret": "s"})

        assert isinstance(a, AlpacaAdapter)
        assert isinstance(b, BinanceAdapter)


# ============================================================
# Order router
# ============================================================

@pytest.mark.asyncio
async def test_order_router_rejects_unknown_broker(patch_db):
    from services.order_router import submit_order
    result = await submit_order(
        user_id="u1",
        broker_id="alpaca",
        ticker="AAPL",
        side="buy",
        qty=1,
    )
    assert result["status"] == "rejected"
    assert "not connected" in result["reason"].lower()


@pytest.mark.asyncio
async def test_order_router_rejects_no_price(patch_db):
    """No cached price → rejected for safety."""
    from services.order_router import submit_order
    from services import data_freshness
    from database import db

    # Set up: connect a broker
    import base64
    await db["brokers"].insert_one({
        "user_id": "u_np",
        "broker_id": "alpaca",
        "credentials": {"api_key": base64.b64encode(b"k").decode(), "api_secret": base64.b64encode(b"s").decode()},
        "paper_mode": True,
    })
    # Make sure no cached price for ZZZZ
    data_freshness.clear_cache()
    result = await submit_order(
        user_id="u_np",
        broker_id="alpaca",
        ticker="ZZZZ",
        side="buy",
        qty=1,
    )
    assert result["status"] == "rejected"
    assert "price" in result["reason"].lower()


@pytest.mark.asyncio
async def test_order_router_live_gate(patch_db, monkeypatch):
    """Even with valid risk + price, live orders need LIVE_TRADING_ENABLED."""
    from services.order_router import submit_order
    from services import data_freshness, risk_engine
    from database import db
    import base64
    import os

    user = "u_live"
    # Set risk limits
    await risk_engine.set_limits(user, {
        "daily_loss_limit_pct": 99,
        "max_drawdown_pct": 99,
        "max_open_trades": 99,
        "max_position_size_pct": 99,
    })
    # Connect a live broker
    await db["brokers"].insert_one({
        "user_id": user,
        "broker_id": "alpaca",
        "credentials": {"api_key": base64.b64encode(b"k").decode(), "api_secret": base64.b64encode(b"s").decode()},
        "paper_mode": False,  # LIVE
    })
    # Set a cached price
    data_freshness.set_price("AAPL", 150)
    # Ensure live trading is NOT enabled
    monkeypatch.delenv("LIVE_TRADING_ENABLED", raising=False)

    result = await submit_order(
        user_id=user,
        broker_id="alpaca",
        ticker="AAPL",
        side="buy",
        qty=1,
        confirm_live=True,
    )
    assert result["status"] == "rejected"
    assert "live trading disabled" in result["reason"].lower()
