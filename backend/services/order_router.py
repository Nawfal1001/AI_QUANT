"""
Live order routing.

Every live broker order flows through:
1. Risk engine check (kill switch, daily loss, max DD, max open, position size)
2. Idempotency check (no duplicate within window)
3. Runtime live-trading control gate
4. Optional frontend/request live confirmation
5. Adapter.place_order() — the real broker call
"""
from datetime import datetime

from database import db
from services import risk_engine, order_idempotency, data_freshness
from services.brokers import make_adapter, BrokerError
from services.credential_crypto import decrypt_secret
from services.logger import child
from services.runtime_controls import get_runtime_controls, is_live_trading_effectively_enabled

log = child("order_router")

col_brokers = db["brokers"]
col_live_orders = db["live_orders"]


def _reveal(s: str) -> str:
    """Decrypt a stored credential. decrypt_secret already handles both the new
    fernet: tokens and legacy Base64 values, so existing connections keep working."""
    return decrypt_secret(s) if s else ""


async def get_broker_connection(user_id: str, broker_id: str):
    """Load the user's saved broker credentials. Returns (adapter, paper_mode) or raises."""
    doc = await col_brokers.find_one({"user_id": user_id, "broker_id": broker_id})
    if not doc:
        raise BrokerError(f"Broker '{broker_id}' is not connected for this user")
    paper_mode = doc.get("paper_mode", True)
    creds_obscured = doc.get("credentials", {})
    creds = {k: _reveal(v) for k, v in creds_obscured.items()}
    adapter = make_adapter(broker_id, creds, paper_mode=paper_mode)
    return adapter, paper_mode


async def submit_order(
    user_id: str,
    broker_id: str,
    ticker: str,
    side: str,
    qty: float,
    order_type: str = "market",
    limit_price: float = None,
    confirm_live: bool = False,
) -> dict:
    """
    Submit a live (broker) order. Returns a normalized result.
    Reject reasons surface clearly in the "reason" field.
    """
    try:
        adapter, paper_mode = await get_broker_connection(user_id, broker_id)
    except BrokerError as e:
        return {"status": "rejected", "reason": str(e)}

    cached = data_freshness.get_price(ticker)
    if not cached:
        return {"status": "rejected", "reason": f"No live price for {ticker} — start the WS price feed or pass current_price"}
    if cached.get("expired"):
        return {"status": "rejected", "reason": f"Price for {ticker} is stale ({cached['age_sec']:.0f}s old)"}
    price = cached["price"]
    position_size_usd = qty * price

    idem = order_idempotency.check_and_record(user_id, ticker, side, qty)
    if not idem["unique"]:
        return {"status": "rejected", "reason": idem["reason"]}

    risk = await risk_engine.check_order(user_id, position_size_usd, ticker)
    if not risk["allowed"]:
        order_idempotency.release(idem["key"])
        return {"status": "rejected", "reason": risk["reason"]}

    if not paper_mode:
        controls = await get_runtime_controls()
        if not await is_live_trading_effectively_enabled():
            order_idempotency.release(idem["key"])
            if controls.get("server_live_hard_lock") and not controls.get("frontend_live_override_allowed"):
                return {"status": "rejected", "reason": "Live trading disabled by server hard lock. Set LIVE_TRADING_ENABLED=true or ALLOW_FRONTEND_LIVE_OVERRIDE=true."}
            return {"status": "rejected", "reason": "Live trading disabled in runtime controls"}
        if controls.get("require_live_confirmation", True) and not confirm_live:
            order_idempotency.release(idem["key"])
            return {"status": "rejected", "reason": "Live order requires confirm_live=true"}

    log.info(f"user {user_id} submitting {broker_id} {'paper' if paper_mode else 'LIVE'} order: {side} {qty} {ticker}")
    try:
        result = await adapter.place_order(ticker=ticker, side=side, qty=qty, order_type=order_type, limit_price=limit_price)
    except Exception as e:
        log.exception(f"adapter.place_order failed: {e}")
        order_idempotency.release(idem["key"])
        return {"status": "rejected", "reason": f"Adapter error: {e}"}

    record = {
        "user_id": user_id,
        "broker_id": broker_id,
        "paper_mode": paper_mode,
        "ticker": ticker.upper(),
        "side": side.lower(),
        "qty": qty,
        "order_type": order_type,
        "limit_price": limit_price,
        "broker_order_id": result.get("broker_order_id"),
        "status": result.get("status"),
        "filled_qty": result.get("filled_qty", 0),
        "fill_price": result.get("fill_price"),
        "mark_price": price,
        "submitted_at": datetime.utcnow().isoformat(),
        "message": result.get("message", ""),
    }
    try:
        ins = await col_live_orders.insert_one(record)
        record["_id"] = str(ins.inserted_id)
    except Exception as e:
        log.exception(f"failed to store live order: {e}")

    log.info(f"order {result.get('broker_order_id')} for user {user_id}: {result.get('status')}")
    return record


async def list_live_orders(user_id: str, limit: int = 50, broker_id: str = None) -> list:
    q = {"user_id": user_id}
    if broker_id:
        q["broker_id"] = broker_id
    docs = await col_live_orders.find(q).sort("submitted_at", -1).limit(limit).to_list(limit)
    for d in docs:
        d["_id"] = str(d["_id"])
    return docs


async def cancel_live_order(user_id: str, broker_id: str, broker_order_id: str) -> dict:
    try:
        adapter, _ = await get_broker_connection(user_id, broker_id)
    except BrokerError as e:
        return {"status": "error", "message": str(e)}
    result = await adapter.cancel_order(broker_order_id)
    if result.get("status") == "cancelled":
        await col_live_orders.update_one({"user_id": user_id, "broker_id": broker_id, "broker_order_id": broker_order_id}, {"$set": {"status": "cancelled", "cancelled_at": datetime.utcnow().isoformat()}})
    return result


async def sync_broker_positions(user_id: str, broker_id: str) -> list:
    try:
        adapter, _ = await get_broker_connection(user_id, broker_id)
        return await adapter.get_positions()
    except BrokerError as e:
        log.warning(f"sync_broker_positions failed: {e}")
        return []
