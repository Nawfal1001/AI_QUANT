"""
OANDA forex broker adapter.

Paper hits api-fxpractice.oanda.com, live hits api-fxtrade.oanda.com.
Docs: https://developer.oanda.com/rest-live-v20/introduction/
"""
import aiohttp

from services.brokers.base import BrokerAdapter, BrokerError
from services.logger import child

log = child("broker.oanda")


class OandaAdapter(BrokerAdapter):
    name = "oanda"

    def __init__(self, credentials: dict, paper_mode: bool = True):
        super().__init__(credentials, paper_mode)
        self.api_key = credentials.get("api_key", "")
        self.account_id = credentials.get("account_id", "")
        self.base = "https://api-fxpractice.oanda.com" if paper_mode else "https://api-fxtrade.oanda.com"
        self._session: "aiohttp.ClientSession | None" = None

    def _headers(self):
        return {
            "Authorization": f"Bearer {self.api_key}",
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

    async def _request(self, method, path, **kwargs):
        url = f"{self.base}{path}"
        s = await self._get_session()
        async with s.request(method, url, headers=self._headers(), **kwargs) as r:
            text = await r.text()
            if r.status >= 400:
                log.warning(f"oanda {method} {path} -> {r.status}: {text[:200]}")
                raise BrokerError(f"OANDA {r.status}: {text[:200]}", r.status)
            try:
                import json
                return json.loads(text) if text else {}
            except ValueError:
                return {}

    async def test_connection(self):
        try:
            data = await self._request("GET", f"/v3/accounts/{self.account_id}/summary")
            acct = data.get("account", {})
            return {
                "status": "connected",
                "balance": float(acct.get("balance", 0)),
                "message": f"OANDA {'practice' if self.paper_mode else 'live'} verified",
            }
        except BrokerError as e:
            return {"status": "auth_failed" if e.status_code == 401 else "test_failed", "message": str(e)}

    async def get_balance(self):
        data = await self._request("GET", f"/v3/accounts/{self.account_id}/summary")
        return float(data.get("account", {}).get("balance", 0))

    async def place_order(self, ticker, side, qty, order_type="market", limit_price=None, time_in_force="gtc"):
        # OANDA uses instrument names like "EUR_USD"
        instrument = ticker.upper().replace("/", "_")
        # OANDA: positive units = buy, negative = sell
        units = qty if side.lower() == "buy" else -qty
        order = {"units": str(units), "instrument": instrument, "timeInForce": "FOK", "type": "MARKET"}
        if order_type == "limit" and limit_price is not None:
            order["type"] = "LIMIT"
            order["price"] = str(limit_price)
            order["timeInForce"] = "GTC"

        try:
            data = await self._request("POST", f"/v3/accounts/{self.account_id}/orders", json={"order": order})
            tx = data.get("orderFillTransaction") or data.get("orderCreateTransaction") or {}
            return {
                "broker_order_id": tx.get("id"),
                "status": "filled" if data.get("orderFillTransaction") else "submitted",
                "filled_qty": abs(float(tx.get("units", 0))),
                "fill_price": float(tx["price"]) if tx.get("price") else None,
                "message": "Order submitted to OANDA",
            }
        except BrokerError as e:
            return {"broker_order_id": None, "status": "rejected", "filled_qty": 0, "fill_price": None, "message": str(e)}

    async def cancel_order(self, broker_order_id):
        try:
            await self._request("PUT", f"/v3/accounts/{self.account_id}/orders/{broker_order_id}/cancel")
            return {"status": "cancelled", "message": "Order cancelled"}
        except BrokerError as e:
            return {"status": "error", "message": str(e)}

    async def get_positions(self):
        try:
            data = await self._request("GET", f"/v3/accounts/{self.account_id}/openPositions")
            out = []
            for p in data.get("positions", []):
                long_units = float(p.get("long", {}).get("units", 0))
                short_units = float(p.get("short", {}).get("units", 0))
                long_avg = float(p.get("long", {}).get("averagePrice") or 0)
                short_avg = float(p.get("short", {}).get("averagePrice") or 0)
                # OANDA can be hedged (simultaneous long+short). Emit one entry per leg
                # so consumers don't see a netted-out misleading row.
                if abs(long_units) >= 1e-9:
                    out.append({
                        "ticker": p.get("instrument"),
                        "qty": long_units,
                        "avg_entry": long_avg,
                        "market_value": float(p.get("long", {}).get("unrealizedPL", 0)),
                        "unrealized_pnl": float(p.get("long", {}).get("unrealizedPL", 0)),
                        "side": "long",
                    })
                if abs(short_units) >= 1e-9:
                    out.append({
                        "ticker": p.get("instrument"),
                        "qty": short_units,
                        "avg_entry": short_avg,
                        "market_value": float(p.get("short", {}).get("unrealizedPL", 0)),
                        "unrealized_pnl": float(p.get("short", {}).get("unrealizedPL", 0)),
                        "side": "short",
                    })
            return out
        except BrokerError as e:
            log.warning(f"get_positions failed: {e}")
            return []

    async def get_order(self, broker_order_id):
        try:
            data = await self._request("GET", f"/v3/accounts/{self.account_id}/orders/{broker_order_id}")
            order = data.get("order", {})
            return {
                "broker_order_id": order.get("id"),
                "status": order.get("state", "unknown").lower(),
                "filled_qty": 0,
                "fill_price": None,
                "message": "",
            }
        except BrokerError as e:
            return {"broker_order_id": broker_order_id, "status": "unknown", "filled_qty": 0, "fill_price": None, "message": str(e)}
