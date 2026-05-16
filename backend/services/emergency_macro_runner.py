"""
Emergency Macro Runner.

Consumes macro_emergency_signals produced by economic_event_engine and executes
only bots with bot_role='emergency_macro' and use_macro_signals=True.
"""
from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Optional

from database import db
from services.logger import child
from services import data_freshness
from services.bots import record_execution
from services.bot_runner import _ensure_price, _calc_position_size

log = child("emergency_macro_runner")

_running = False
_task: Optional[asyncio.Task] = None


async def _active_emergency_bots():
    return await db["bots"].find({
        "enabled": True,
        "bot_role": "emergency_macro",
        "use_macro_signals": True,
    }).to_list(100)


async def _claim_signal(sig: dict) -> bool:
    res = await db["macro_emergency_signals"].update_one(
        {"_id": sig["_id"], "status": {"$in": ["ready", "pending_confirmation"]}},
        {"$set": {"status": "processing", "processing_at": datetime.utcnow().isoformat()}},
    )
    return res.modified_count == 1


async def _process_signal_for_bot(sig: dict, bot: dict):
    user_id = bot["user_id"]
    bot_id = bot["_id"]
    ticker = sig["ticker"].upper()
    asset_type = sig.get("asset_type", "forex")
    signal_str = sig.get("signal", "HOLD")
    confidence = float(sig.get("confidence", 0) or 0)

    if confidence < float(bot.get("min_confidence", 70) or 70):
        await record_execution(user_id, bot_id, ticker, asset_type, signal_str, confidence, "skipped", reason="macro signal below bot min_confidence")
        return False

    cached = await _ensure_price(ticker, asset_type, bot.get("schedule", "5m"))
    if not cached:
        await record_execution(user_id, bot_id, ticker, asset_type, signal_str, confidence, "rejected", reason="no fresh price for emergency macro signal")
        return False

    price = cached["price"]
    qty = await _calc_position_size(user_id, bot, price)
    if qty <= 0:
        await record_execution(user_id, bot_id, ticker, asset_type, signal_str, confidence, "rejected", reason="size = 0")
        return False

    side = "buy" if "BUY" in signal_str else "sell"
    broker = bot.get("broker", "paper")
    try:
        if broker == "paper":
            from services import paper_broker
            result = await paper_broker.place_order(
                user_id=user_id,
                ticker=ticker,
                side=side,
                qty=qty,
                order_type="market",
                current_price=price,
                asset_type=asset_type,
                skip_freshness=False,
            )
        else:
            from services.order_router import submit_order
            result = await submit_order(user_id=user_id, broker_id=broker, ticker=ticker, side=side, qty=qty, order_type="market", confirm_live=True)
    except Exception as e:
        log.exception(f"emergency macro order failed for {ticker}: {e}")
        await record_execution(user_id, bot_id, ticker, asset_type, signal_str, confidence, "rejected", reason=f"macro order error: {e}")
        return False

    status = result.get("status")
    result.setdefault("bot_context", {"source": "macro_emergency", "event_id": sig.get("event_id"), "macro_context": sig.get("macro_context")})
    if status in {"filled", "submitted"}:
        await record_execution(user_id, bot_id, ticker, asset_type, signal_str, confidence, "placed", order_result=result, reason=sig.get("reason", "macro emergency signal"))
        return True
    await record_execution(user_id, bot_id, ticker, asset_type, signal_str, confidence, "rejected", order_result=result, reason=result.get("reason") or result.get("message", "unknown"))
    return False


async def _runner_loop():
    global _running
    log.info("emergency_macro_runner started")
    while _running:
        try:
            from services.runtime_controls import is_emergency_macro_enabled
            if not await is_emergency_macro_enabled():
                await asyncio.sleep(10)
                continue
            now = datetime.utcnow().isoformat()
            signals = await db["macro_emergency_signals"].find({
                "expires_at": {"$gte": now},
                "status": {"$in": ["ready", "pending_confirmation"]},
            }).sort("created_at", -1).limit(20).to_list(20)
            if signals:
                bots = await _active_emergency_bots()
                for sig in signals:
                    if not await _claim_signal(sig):
                        continue
                    placed = 0
                    for bot in bots:
                        wl = bot.get("watchlist") or []
                        if wl and sig["ticker"].upper() not in {x.get("ticker", "").upper() for x in wl}:
                            # Emergency bots may opt into all macro signals.
                            if not bot.get("trade_all_macro_signals", True):
                                continue
                        ok = await _process_signal_for_bot(sig, bot)
                        placed += 1 if ok else 0
                    await db["macro_emergency_signals"].update_one({"_id": sig["_id"]}, {"$set": {"status": "executed" if placed else "skipped", "executed_at": datetime.utcnow().isoformat(), "orders_placed": placed}})
        except asyncio.CancelledError:
            break
        except Exception as e:
            log.exception(f"emergency macro runner error: {e}")
        try:
            await asyncio.sleep(10)
        except asyncio.CancelledError:
            break
    log.info("emergency_macro_runner stopped")


async def start_emergency_macro_runner():
    global _running, _task
    if _running:
        return {"status": "already_running"}
    _running = True
    _task = asyncio.create_task(_runner_loop())
    return {"status": "started"}


async def stop_emergency_macro_runner():
    global _running, _task
    _running = False
    if _task:
        _task.cancel()
        _task = None
    return {"status": "stopped"}


def is_running() -> bool:
    return _running
