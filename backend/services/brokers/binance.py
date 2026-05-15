"""
Binance broker adapter via ccxt.

Binance has no paper-trading API for spot, so paper_mode is informational only;
real trades will execute on live spot. The router enforces paper_mode for safety.
"""
import asyncio

from services.brokers.base import BrokerAdapter, BrokerError
from services.logger import child

log = child("broker.binance")


class BinanceAdapter(BrokerAdapter):
    name = "binance"

    def __init__(self, credentials: dict, paper_mode: bool = True):
        super().__init__(credentials, paper_mode)
        import ccxt
        self.client = ccxt.binance({
            "apiKey": credentials.get("api_key", ""),
            "secret": credentials.get("api_secret", ""),
            "enableRateLimit": True,
        })

    async def _run(self, fn, *args, **kwargs):
        """Run sync ccxt method in executor — ccxt is sync by default."""
        loop = asyncio.get_event_loop()
        try:
            return await loop.run_in_executor(None, lambda: fn(*args, **kwargs))
        except Exception as e:
            raise BrokerError(f"Binance: {e}")

    @staticmethod
    def _pair(ticker: str) -> str:
        t = ticker.upper().replace("/USDT", "")
        return f"{t}/USDT"

    async def test_connection(self) -> dict:
        try:
            bal = await self._run(self.client.fetch_balance)
            usdt = bal.get("USDT", {}).get("free", 0)
            return {
                "status": "connected",
                "balance": float(usdt),
                "message": "Binance spot account verified",
            }
        except BrokerError as e:
            return {"status": "auth_failed", "message": str(e)}

    async def get_balance(self) -> float:
        bal = await self._run(self.client.fetch_balance)
        return float(bal.get("USDT", {}).get("free", 0))

    async def place_order(self, ticker, side, qty, order_type="market", limit_price=None, time_in_force="gtc"):
        if self.paper_mode:
            # Binance spot has no paper mode — block here
            return {"broker_order_id": None, "status": "rejected", "filled_qty": 0, "fill_price": None,
                    "message": "Binance does not support paper trading. Use the platform's internal paper broker instead."}
        pair = self._pair(ticker)
        try:
            if order_type == "market":
                data = await self._run(self.client.create_market_order, pair, side.lower(), qty)
            else:
                if limit_price is None:
                    raise BrokerError("limit_price required for limit order")
                data = await self._run(self.client.create_limit_order, pair, side.lower(), qty, limit_price)
            return {
                "broker_order_id": str(data.get("id")),
                "status": "submitted" if data.get("status") == "open" else data.get("status", "submitted"),
                "filled_qty": float(data.get("filled", 0)),
                "fill_price": float(data["average"]) if data.get("average") else None,
                "message": "Order submitted to Binance",
            }
        except BrokerError as e:
            return {"broker_order_id": None, "status": "rejected", "filled_qty": 0, "fill_price": None, "message": str(e)}

    async def cancel_order(self, broker_order_id):
        # ccxt requires symbol — would need to look it up. Skip for now.
        return {"status": "error", "message": "Cancel not implemented for Binance adapter (needs symbol)"}

    async def get_positions(self):
        try:
            bal = await self._run(self.client.fetch_balance)
            out = []
            for asset, info in bal.get("total", {}).items():
                if info > 0 and asset != "USDT":
                    out.append({
                        "ticker": asset,
                        "qty": float(info),
                        "avg_entry": 0,  # Binance spot doesn't track avg entry
                        "market_value": 0,
                        "unrealized_pnl": 0,
                    })
            return out
        except BrokerError as e:
            log.warning(f"get_positions failed: {e}")
            return []

    async def get_order(self, broker_order_id):
        return {"broker_order_id": broker_order_id, "status": "unknown", "filled_qty": 0, "fill_price": None,
                "message": "get_order not implemented for Binance (needs symbol)"}
