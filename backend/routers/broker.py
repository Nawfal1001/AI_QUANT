"""
Broker router — user-scoped, uses adapter layer for real broker calls.

Order placement flow:
- POST /broker/order -> order_router.submit_order
- That goes through risk + idempotency + live-mode gate + adapter
"""
import re
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from database import db
from middleware.auth import get_current_user
from services.brokers import make_adapter, BrokerError
from services.order_router import submit_order, list_live_orders, cancel_live_order, sync_broker_positions
from services.credential_crypto import encrypt_secret, decrypt_secret, mask_secret
from services.logger import child

log = child("broker_router")
router = APIRouter()
col = db["brokers"]

TICKER_RE = re.compile(r"^[A-Z0-9._\-/]{1,20}$")


BROKER_SPECS = [
    {"id": "alpaca", "name": "Alpaca", "type": "stocks", "fields": ["api_key", "api_secret"], "supports_paper": True, "docs_url": "https://alpaca.markets/docs/"},
    {"id": "binance", "name": "Binance", "type": "crypto", "fields": ["api_key", "api_secret"], "supports_paper": False, "docs_url": "https://binance-docs.github.io/apidocs/"},
    {"id": "oanda", "name": "OANDA", "type": "forex", "fields": ["api_key", "account_id"], "supports_paper": True, "docs_url": "https://developer.oanda.com/"},
]


@router.get("/available")
async def available():
    # Public: lists supported brokers + required field names. No user data.
    return {"brokers": BROKER_SPECS}


@router.post("/connect")
async def connect(data: dict, user=Depends(get_current_user)):
    """Connect or update broker credentials. Tests live by calling the adapter."""
    broker = data.get("broker")
    if broker not in [b["id"] for b in BROKER_SPECS]:
        raise HTTPException(400, f"Unsupported broker: {broker}")
    spec = next(b for b in BROKER_SPECS if b["id"] == broker)

    creds_plain = {}
    creds_obscured = {}
    for f in spec["fields"]:
        v = data.get(f, "")
        if not isinstance(v, str) or not v.strip():
            raise HTTPException(400, f"Missing field: {f}")
        if len(v) > 512:
            raise HTTPException(400, f"Field too long: {f}")
        creds_plain[f] = v
        creds_obscured[f] = encrypt_secret(v)

    paper_mode = bool(data.get("paper_mode", True))

    try:
        adapter = make_adapter(broker, creds_plain, paper_mode=paper_mode)
        test = await adapter.test_connection()
    except BrokerError as e:
        log.warning(f"broker connect test failed: {e}")
        test = {"status": "test_failed", "message": "Broker rejected credentials"}
    except Exception as e:
        log.exception(f"connect test failed: {e}")
        test = {"status": "test_failed", "message": "Connection test failed"}

    doc = {
        "user_id": user["id"],
        "broker_id": broker,
        "credentials": creds_obscured,
        "paper_mode": paper_mode,
        "connected_at": datetime.utcnow().isoformat(),
        "status": test.get("status", "unknown"),
        "balance": test.get("balance"),
        "test_message": test.get("message", ""),
    }
    await col.replace_one({"user_id": user["id"], "broker_id": broker}, doc, upsert=True)
    log.info(f"user {user['id']} connected broker {broker} status={test.get('status')}")
    return {
        "status": test.get("status"),
        "broker": broker,
        "paper_mode": paper_mode,
        "balance": test.get("balance"),
        "message": test.get("message", ""),
    }


@router.get("/status")
async def status(user=Depends(get_current_user)):
    docs = await col.find({"user_id": user["id"]}).to_list(20)
    out = []
    for d in docs:
        out.append({
            "broker_id": d.get("broker_id"),
            "status": d.get("status", "unknown"),
            "paper_mode": d.get("paper_mode", True),
            "balance": d.get("balance"),
            "connected_at": d.get("connected_at"),
            "api_key_masked": mask_secret(decrypt_secret(d.get("credentials", {}).get("api_key", ""))),
        })
    return {"connected": out}


@router.delete("/{broker}")
async def disconnect(broker: str, user=Depends(get_current_user)):
    res = await col.delete_one({"user_id": user["id"], "broker_id": broker})
    return {"deleted": res.deleted_count, "broker": broker}


class BrokerOrderIn(BaseModel):
    broker: str = Field("alpaca", max_length=24)
    ticker: str = Field(..., min_length=1, max_length=20)
    side: str = Field("buy", pattern=r"^(?i)(buy|sell)$")
    qty: float = Field(..., gt=0, le=1_000_000_000)
    order_type: str = Field("market", pattern=r"^(market|limit|stop)$")
    limit_price: Optional[float] = Field(None, gt=0, le=1_000_000_000)
    confirm_live: bool = False


@router.post("/order")
async def order(payload: BrokerOrderIn, user=Depends(get_current_user)):
    """Place a real broker order. Goes through risk + idempotency + adapter."""
    ticker = payload.ticker.upper().strip()
    if not TICKER_RE.match(ticker):
        raise HTTPException(400, "Invalid ticker format")
    if payload.broker not in [b["id"] for b in BROKER_SPECS]:
        raise HTTPException(400, f"Unsupported broker: {payload.broker}")

    result = await submit_order(
        user_id=user["id"],
        broker_id=payload.broker,
        ticker=ticker,
        side=payload.side.lower(),
        qty=payload.qty,
        order_type=payload.order_type,
        limit_price=payload.limit_price,
        confirm_live=payload.confirm_live,
    )
    if result.get("status") == "rejected":
        raise HTTPException(400, result.get("reason") or result.get("message") or "Order rejected")
    return result


@router.get("/orders")
async def orders(limit: int = 50, broker: str = None, user=Depends(get_current_user)):
    return {"orders": await list_live_orders(user["id"], limit, broker_id=broker)}


@router.post("/order/{broker}/{broker_order_id}/cancel")
async def cancel(broker: str, broker_order_id: str, user=Depends(get_current_user)):
    return await cancel_live_order(user["id"], broker, broker_order_id)


@router.get("/positions/{broker}")
async def positions(broker: str, user=Depends(get_current_user)):
    """Fetch positions directly from the broker (live, not cached)."""
    return {"positions": await sync_broker_positions(user["id"], broker)}


@router.get("/balance/{broker}")
async def balance(broker: str, user=Depends(get_current_user)):
    """Fetch fresh balance from the broker."""
    doc = await col.find_one({"user_id": user["id"], "broker_id": broker})
    if not doc:
        raise HTTPException(404, f"Broker {broker} not connected")
    creds = {k: decrypt_secret(v) for k, v in doc.get("credentials", {}).items()}
    try:
        adapter = make_adapter(broker, creds, paper_mode=doc.get("paper_mode", True))
        bal = await adapter.get_balance()
        await col.update_one({"_id": doc["_id"]}, {"$set": {"balance": bal}})
        return {"broker": broker, "balance": bal}
    except BrokerError as e:
        log.warning(f"broker balance fetch failed: {e}")
        raise HTTPException(400, "Failed to fetch balance from broker")
