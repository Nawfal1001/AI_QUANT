import asyncio
from datetime import datetime
from typing import Dict, Set

import ccxt
import yfinance as yf
from fastapi import WebSocket

from services.logger import child

log = child("websocket")

CRYPTO = {"BTC", "ETH", "BNB", "SOL", "ADA", "XRP", "DOGE", "AVAX", "MATIC", "DOT", "LINK", "UNI"}


class Manager:
    def __init__(self):
        self.subs: Dict[str, Set[WebSocket]] = {}
        self.client_subs: Dict[WebSocket, Set[str]] = {}
        # Track user_id per connection for audit
        self.client_user: Dict[WebSocket, str] = {}

    async def connect(self, ws: WebSocket):
        """Accept + register. Used by routes that handle auth internally."""
        await ws.accept()
        self.client_subs[ws] = set()

    def register_authenticated(self, ws: WebSocket, user_id: str):
        """Register a socket that is already accepted (e.g. after auth)."""
        self.client_subs[ws] = set()
        self.client_user[ws] = user_id

    def disconnect(self, ws: WebSocket):
        for t in self.client_subs.get(ws, set()):
            if t in self.subs:
                self.subs[t].discard(ws)
        self.client_subs.pop(ws, None)
        self.client_user.pop(ws, None)

    def subscribe(self, ws: WebSocket, tickers: list):
        for t in tickers:
            if t not in self.subs:
                self.subs[t] = set()
            self.subs[t].add(ws)
            self.client_subs.setdefault(ws, set()).add(t)

    def unsubscribe(self, ws: WebSocket, tickers: list):
        for t in tickers:
            if t in self.subs:
                self.subs[t].discard(ws)
            self.client_subs.get(ws, set()).discard(t)

    async def broadcast(self, ticker: str, data: dict):
        if ticker not in self.subs:
            return
        dead = set()
        for ws in list(self.subs[ticker]):
            try:
                await ws.send_json(data)
            except Exception as e:
                log.debug(f"broadcast failed for one client: {e}")
                dead.add(ws)
        for ws in dead:
            self.disconnect(ws)

    async def send(self, ws: WebSocket, data: dict):
        try:
            await ws.send_json(data)
        except Exception as e:
            log.debug(f"send failed: {e}")
            self.disconnect(ws)


manager = Manager()


def _fetch(by_type):
    prices = {}
    if by_type.get("stock"):
        try:
            tks = " ".join(by_type["stock"])
            data = yf.download(tks, period="1d", interval="1m", progress=False, auto_adjust=True)
            if len(by_type["stock"]) == 1:
                t = by_type["stock"][0]
                if "Close" in data.columns and not data.empty:
                    prices[t] = {"price": round(float(data["Close"].iloc[-1]), 2), "change_pct": 0}
            else:
                for t in by_type["stock"]:
                    try:
                        prices[t] = {"price": round(float(data["Close"][t].dropna().iloc[-1]), 2), "change_pct": 0}
                    except Exception as e:
                        log.debug(f"_fetch stock {t} failed: {e}")
        except Exception as e:
            log.debug(f"_fetch stock batch failed: {e}")
    if by_type.get("crypto"):
        try:
            ex = ccxt.binance()
            pairs = [f"{t}/USDT" for t in by_type["crypto"]]
            td = ex.fetch_tickers(pairs)
            for t in by_type["crypto"]:
                p = f"{t}/USDT"
                if p in td:
                    prices[t] = {"price": td[p].get("last", 0), "change_pct": round(td[p].get("percentage", 0) or 0, 2)}
        except Exception as e:
            log.debug(f"_fetch crypto failed: {e}")
    return prices


async def broadcast_loop():
    loop = asyncio.get_event_loop()
    while True:
        try:
            if manager.subs:
                all_t = list(manager.subs.keys())
                by_type = {"stock": [t for t in all_t if t not in CRYPTO], "crypto": [t for t in all_t if t in CRYPTO]}
                # Cap each cycle at 10s so a hung yfinance/ccxt call cannot stall
                # the whole websocket fanout.
                try:
                    prices = await asyncio.wait_for(loop.run_in_executor(None, _fetch, by_type), timeout=10)
                except asyncio.TimeoutError:
                    log.warning("broadcast_loop fetch timeout")
                    prices = {}
                now = datetime.utcnow().isoformat()
                for ticker, d in prices.items():
                    await manager.broadcast(ticker, {
                        "type": "price",
                        "ticker": ticker,
                        "price": d.get("price", 0),
                        "change_pct": d.get("change_pct", 0),
                        "timestamp": now,
                    })

                try:
                    from services.data_freshness import set_price
                    for ticker, d in prices.items():
                        set_price(ticker, d.get("price", 0), ttl_sec=15, source="ws")
                except Exception as e:
                    log.debug(f"freshness cache update failed: {e}")

                # Also trip any resting paper limit/stop orders against the new prices.
                try:
                    from services.paper_broker import match_resting_orders
                    price_map = {t: d.get("price", 0) for t, d in prices.items()}
                    await match_resting_orders(price_map)
                except Exception as e:
                    log.debug(f"paper resting-order match failed: {e}")
        except asyncio.CancelledError:
            log.info("broadcast_loop cancelled")
            return
        except Exception as e:
            log.exception(f"broadcast_loop error: {e}")
        try:
            await asyncio.sleep(3)
        except asyncio.CancelledError:
            return
