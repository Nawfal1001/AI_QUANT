"""
Broker router — user-scoped, uses adapter layer for real broker calls.

Order placement flow:
- POST /broker/order -> order_router.submit_order
- That goes through risk + idempotency + live-mode gate + adapter
"""
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException

from database import db
from middleware.auth import get_current_user
from services.brokers import make_adapter, BrokerError
from services.order_router import submit_order, list_live_orders, cancel_live_order, sync_broker_positions
from services.logger import child
from services.credential_crypto import encrypt_secret, decrypt_secret, mask_secret

log = child("broker_router")
router = APIRouter()
col = db["brokers"]

BROKER_SPECS = [
    {"id": "alpaca", "name": "Alpaca", "type": "stocks", "fields": ["api_key", "api_secret"], "supports_paper": True, "docs_url": "https://alpaca.markets/docs/"},
    {"id": "binance", "name": "Binance", "type": "crypto", "fields": ["api_key", "api_secret"], "supports_paper": False, "docs_url": "https://binance-docs.github.io/apidocs/"},
    {"id": "oanda", "name": "OANDA", "type": "forex", "fields": ["api_key", "account_id"], "supports_paper": True, "docs_url": "https://developer.oanda.com/"},
]


@router.get("/available")
async def available():
    return {"brokers": BROKER_SPECS}


@router.post("/connect")
async def connect(data: dict, user=Depends(get_current_user)):
    broker = data.get("broker")
    if broker not in [b["id"] for b in BROKER_SPECS]:
        raise HTTPException(400, f"Unsupported broker: {broker}")
    spec = next(b for b in BROKER_SPECS if b["id"] == broker)

    creds_plain = {}
    creds_obscured = {}
    for f in spec["fields"]:
        v = data.get(f, "")
        if not v:
            raise HTTPException(400, f"Missing field: {f}")
        creds_plain[f] = v
        creds_obscured[f] = encrypt_secret(v)

    paper_mode = bool(data.get("paper_mode", True))

    try:
        adapter = make_adapter(broker, creds_plain, paper_mode=paper_mode)
        test = await adapter.test_connection()
    except BrokerError as e:
        test = {"status": "test_failed", "message": str(e)}
    except Exception as e:
        log.exception(f"connect test failed: {e}")
        test = {"status": "test_failed", "message": str(e)}

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


@router.post("/order")
async def order(data: dict, user=Depends(get_current_user)):
    broker = data.get("broker", "alpaca")
    ticker = data.get("ticker", "").upper()
    side = data.get("side", "buy")
    qty = float(data.get("qty", 0))
    order_type = data.get("order_type", "market")
    limit_price = data.get("limit_price")
    confirm_live = bool(data.get("confirm_live", False))

    if not ticker or qty <= 0:
        raise HTTPException(400, "ticker and qty>0 required")

    result = await submit_order(
        user_id=user["id"],
        broker_id=broker,
        ticker=ticker,
        side=side,
        qty=qty,
        order_type=order_type,
        limit_price=limit_price,
        confirm_live=confirm_live,
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
    return {"positions": await sync_broker_positions(user["id"], broker)}


@router.get("/balance/{broker}")
async def balance(broker: str, user=Depends(get_current_user)):
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
        raise HTTPException(400, str(e))
