"""
Alpaca broker adapter.

Uses Alpaca's REST API directly. Paper mode hits paper-api.alpaca.markets,
live hits api.alpaca.markets.

Docs: https://docs.alpaca.markets/reference/
"""
import aiohttp

from services.brokers.base import BrokerAdapter, BrokerError
from services.logger import child

log = child("broker.alpaca")


class AlpacaAdapter(BrokerAdapter):
    name = "alpaca"

    def __init__(self, credentials: dict, paper_mode: bool = True):
        super().__init__(credentials, paper_mode)
        self.api_key = credentials.get("api_key", "")
        self.api_secret = credentials.get("api_secret", "")
        self.base = "https://paper-api.alpaca.markets" if paper_mode else "https://api.alpaca.markets"
        self._session: "aiohttp.ClientSession | None" = None

    def _headers(self):
        return {
            "APCA-API-KEY-ID": self.api_key,
            "APCA-API-SECRET-KEY": self.api_secret,
            "Content-Type": "application/json",
        }

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            timeout = aiohttp.ClientTimeout(total=15)
            self._session = aiohttp.ClientSession(timeout=timeout)
        return self._session

    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()

    async def _request(self, method: str, path: str, **kwargs):
        url = f"{self.base}{path}"
        s = await self._get_session()
        async with s.request(method, url, headers=self._headers(), **kwargs) as r:
            text = await r.text()
            if r.status >= 400:
                log.warning(f"alpaca {method} {path} -> {r.status}: {text[:200]}")
                raise BrokerError(f"Alpaca {r.status}: {text[:200]}", r.status)
            try:
                import json
                return json.loads(text) if text else {}
            except ValueError:
                return {"raw": text}

    async def test_connection(self) -> dict:
        try:
            data = await self._request("GET", "/v2/account")
            return {
                "status": "connected",
                "balance": float(data.get("cash", 0)),
                "message": f"Alpaca {'paper' if self.paper_mode else 'live'} account verified",
            }
        except BrokerError as e:
            return {"status": "auth_failed" if e.status_code == 401 else "test_failed", "message": str(e)}

    async def get_balance(self) -> float:
        data = await self._request("GET", "/v2/account")
        return float(data.get("cash", 0))

    async def place_order(self, ticker, side, qty, order_type="market", limit_price=None, time_in_force="gtc"):
        payload = {
            "symbol": ticker.upper(),
            "qty": str(qty),
            "side": side.lower(),
            "type": order_type,
            "time_in_force": time_in_force if order_type == "limit" else "day",
        }
        if order_type == "limit" and limit_price is not None:
            payload["limit_price"] = str(limit_price)

        try:
            data = await self._request("POST", "/v2/orders", json=payload)
            return {
                "broker_order_id": data.get("id"),
                "status": data.get("status", "submitted"),
                "filled_qty": float(data.get("filled_qty", 0)),
                "fill_price": float(data["filled_avg_price"]) if data.get("filled_avg_price") else None,
                "message": "Order submitted to Alpaca",
            }
        except BrokerError as e:
            return {"broker_order_id": None, "status": "rejected", "filled_qty": 0, "fill_price": None, "message": str(e)}

    async def cancel_order(self, broker_order_id):
        try:
            await self._request("DELETE", f"/v2/orders/{broker_order_id}")
            return {"status": "cancelled", "message": "Order cancelled"}
        except BrokerError as e:
            return {"status": "error", "message": str(e)}

    async def get_positions(self):
        try:
            data = await self._request("GET", "/v2/positions")
            return [
                {
                    "ticker": p.get("symbol"),
                    "qty": float(p.get("qty", 0)),
                    "avg_entry": float(p.get("avg_entry_price", 0)),
                    "market_value": float(p.get("market_value", 0)),
                    "unrealized_pnl": float(p.get("unrealized_pl", 0)),
                }
                for p in data
            ]
        except BrokerError as e:
            log.warning(f"get_positions failed: {e}")
            return []

    async def get_order(self, broker_order_id):
        try:
            data = await self._request("GET", f"/v2/orders/{broker_order_id}")
            return {
                "broker_order_id": data.get("id"),
                "status": data.get("status", "unknown"),
                "filled_qty": float(data.get("filled_qty", 0)),
                "fill_price": float(data["filled_avg_price"]) if data.get("filled_avg_price") else None,
                "message": "",
            }
        except BrokerError as e:
            return {"broker_order_id": broker_order_id, "status": "unknown", "filled_qty": 0, "fill_price": None, "message": str(e)}
