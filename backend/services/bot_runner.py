"""
Bot Runner.

Background asyncio task that:
1. Loops every 30 seconds
2. Fetches all enabled bots
3. For each bot whose schedule window has elapsed:
   - Loads strategy (built-in or user-defined)
   - Iterates over its watchlist
   - Generates signal on each ticker
   - If signal >= min_confidence, sends order through order_router (paper or live broker)
   - Records execution
   - Updates next_run_at

Failures are logged and never crash the loop.
"""
import asyncio
from datetime import datetime, timedelta
from typing import Optional

import pandas as pd

from database import db
from services.logger import child
from services.bots import (
    get_active_bots, record_execution, SCHEDULES,
)
from services import data_freshness
from services.strategies import STRATEGIES
from services.custom_strategy import run_custom_strategy
from services.backtest_engine import fetch_history

log = child("bot_runner")

_running = False
_task: Optional[asyncio.Task] = None


def _parse_dt(s: Optional[str]) -> Optional[datetime]:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s)
    except Exception:
        return None


async def _load_user_strategy(user_id: str, strategy_id: str) -> Optional[dict]:
    """Load a user-defined strategy from the DB."""
    from bson import ObjectId
    try:
        oid = ObjectId(strategy_id)
    except Exception:
        return None
    return await db["user_strategies"].find_one({"_id": oid, "user_id": user_id})


async def _generate_signal(strategy_type: str, strategy_id: str, user_id: str,
                            ticker: str, asset_type: str) -> Optional[dict]:
    """Run the bot's strategy on the latest ~50 bars. Returns the signal dict or None on failure."""
    # Fetch last ~60 days of daily data — enough for any built-in indicator window.
    end = datetime.utcnow().strftime("%Y-%m-%d")
    start = (datetime.utcnow() - timedelta(days=90)).strftime("%Y-%m-%d")

    try:
        df = await fetch_history(ticker, asset_type, start, end, "1d")
    except Exception as e:
        log.warning(f"fetch_history failed for {ticker}: {e}")
        return None

    if df is None or len(df) < 30:
        return {"signal": "HOLD", "confidence": 0, "reason": "insufficient history"}

    window = df.iloc[-50:]

    try:
        if strategy_type == "builtin":
            fn = STRATEGIES.get(strategy_id)
            if not fn:
                return {"signal": "HOLD", "confidence": 0, "reason": f"unknown strategy {strategy_id}"}
            return fn(window)
        else:
            strat_def = await _load_user_strategy(user_id, strategy_id)
            if not strat_def:
                return {"signal": "HOLD", "confidence": 0, "reason": "user strategy missing"}
            return run_custom_strategy(strat_def, window)
    except Exception as e:
        log.exception(f"signal generation failed for bot strategy {strategy_id} on {ticker}: {e}")
        return None


async def _calc_position_size(user_id: str, bot: dict, price: float) -> float:
    """How many units to buy based on sizing rules and current equity."""
    from services import risk_engine
    equity = await risk_engine.get_account_equity(user_id)

    mode = bot.get("sizing_mode", "fixed_pct")
    sizing_pct = float(bot.get("sizing_pct", 1.0))
    target_dollars = equity * (sizing_pct / 100)

    # Cap by max_position_size_pct from risk limits — defence in depth
    limits = await risk_engine.get_limits(user_id) or {}
    max_pos_pct = float(limits.get("max_position_size_pct", 100))
    cap_dollars = equity * (max_pos_pct / 100)
    target_dollars = min(target_dollars, cap_dollars)

    if mode == "fixed_pct":
        return target_dollars / price if price > 0 else 0
    elif mode == "kelly":
        # Simple Kelly bet sizing — uses historical bot win rate if we have it.
        # Fallback to half-Kelly with 55% / 1.5 R:R if no history.
        from services import signal_tracker
        stats = await signal_tracker.get_stats(user_id, "strategy")
        bot_stats = next((s for s in stats if s["key"] == bot.get("strategy_id")), None)
        if bot_stats and bot_stats["total"] >= 5:
            w = bot_stats["win_rate"] / 100
            edge = w - (1 - w)
            kelly_frac = max(0.0, min(0.25, edge))  # half-Kelly cap
        else:
            kelly_frac = 0.02  # 2% as default
        return (equity * kelly_frac) / price if price > 0 else 0
    elif mode == "atr_volatility":
        # Risk a fixed % of equity, with size inversely proportional to ATR
        # Falls back to fixed_pct if we don't have ATR
        return target_dollars / price if price > 0 else 0
    return 0


async def _process_bot(bot: dict):
    """Run one bot through one cycle. Catches all exceptions."""
    user_id = bot["user_id"]
    bot_id = bot["_id"]
    bot_name = bot.get("name", "?")

    log.info(f"running bot {bot_name} ({bot_id}) for user {user_id}")

    signals_fired = 0
    orders_placed = 0
    orders_rejected = 0

    for item in bot["watchlist"]:
        ticker = item["ticker"].upper()
        asset_type = item.get("asset_type", "stock")

        sig = await _generate_signal(
            strategy_type=bot["strategy_type"],
            strategy_id=bot["strategy_id"],
            user_id=user_id,
            ticker=ticker,
            asset_type=asset_type,
        )
        if not sig:
            await record_execution(user_id, bot_id, ticker, asset_type, "HOLD", 0,
                                   "skipped", reason="signal generation failed")
            continue

        signal_str = sig.get("signal", "HOLD")
        confidence = float(sig.get("confidence", 0))

        # Skip non-actionable or below-threshold signals
        if signal_str == "HOLD" or "BUY" not in signal_str and "SELL" not in signal_str:
            await record_execution(user_id, bot_id, ticker, asset_type, signal_str, confidence,
                                   "skipped", reason="HOLD signal")
            continue

        if confidence < bot.get("min_confidence", 60):
            await record_execution(user_id, bot_id, ticker, asset_type, signal_str, confidence,
                                   "skipped", reason=f"below min_confidence ({confidence} < {bot['min_confidence']})")
            continue

        signals_fired += 1

        # Need a current price for sizing
        cached = data_freshness.get_price(ticker)
        if not cached:
            # Bot can't size without a price — try fetching one once
            try:
                df_tail = await fetch_history(ticker, asset_type,
                                              (datetime.utcnow() - timedelta(days=5)).strftime("%Y-%m-%d"),
                                              datetime.utcnow().strftime("%Y-%m-%d"), "1d")
                if df_tail is not None and len(df_tail):
                    price = float(df_tail["close"].iloc[-1])
                    # Cache it briefly so the order router can use it too
                    data_freshness.set_price(ticker, price, ttl_sec=120, source="bot")
                    cached = {"price": price}
                else:
                    await record_execution(user_id, bot_id, ticker, asset_type, signal_str, confidence,
                                           "rejected", reason="no price available")
                    orders_rejected += 1
                    continue
            except Exception as e:
                log.warning(f"price fetch failed for {ticker}: {e}")
                await record_execution(user_id, bot_id, ticker, asset_type, signal_str, confidence,
                                       "rejected", reason=f"price fetch failed: {e}")
                orders_rejected += 1
                continue

        price = cached["price"]
        qty = await _calc_position_size(user_id, bot, price)
        if qty <= 0:
            await record_execution(user_id, bot_id, ticker, asset_type, signal_str, confidence,
                                   "rejected", reason="size = 0")
            orders_rejected += 1
            continue

        side = "buy" if "BUY" in signal_str else "sell"
        broker = bot.get("broker", "paper")

        try:
            if broker == "paper":
                from services import paper_broker
                result = await paper_broker.place_order(
                    user_id=user_id, ticker=ticker, side=side, qty=qty,
                    order_type="market", current_price=price,
                    asset_type=asset_type, skip_freshness=False,
                )
            else:
                from services.order_router import submit_order
                result = await submit_order(
                    user_id=user_id, broker_id=broker, ticker=ticker,
                    side=side, qty=qty, order_type="market",
                    confirm_live=True,  # bots fire confirmed orders by design
                )
        except Exception as e:
            log.exception(f"bot {bot_name} order failed for {ticker}: {e}")
            await record_execution(user_id, bot_id, ticker, asset_type, signal_str, confidence,
                                   "rejected", reason=f"order error: {e}")
            orders_rejected += 1
            continue

        status = result.get("status")
        if status == "filled" or status == "submitted":
            orders_placed += 1
            await record_execution(user_id, bot_id, ticker, asset_type, signal_str, confidence,
                                   "placed", order_result=result)
            log.info(f"bot {bot_name} placed {side} {qty:.4f} {ticker} @ {price:.2f} (sig {confidence}%)")
        else:
            orders_rejected += 1
            await record_execution(user_id, bot_id, ticker, asset_type, signal_str, confidence,
                                   "rejected", order_result=result,
                                   reason=result.get("reason") or result.get("message", "unknown"))

    # Update bot bookkeeping
    from bson import ObjectId
    schedule_secs = SCHEDULES.get(bot.get("schedule", "1h"), 3600)
    now = datetime.utcnow()
    next_run = now + timedelta(seconds=schedule_secs)

    await db["bots"].update_one(
        {"_id": ObjectId(bot_id)},
        {
            "$set": {
                "last_run_at": now.isoformat(),
                "next_run_at": next_run.isoformat(),
            },
            "$inc": {
                "stats.runs": 1,
                "stats.signals_fired": signals_fired,
                "stats.orders_placed": orders_placed,
                "stats.orders_rejected": orders_rejected,
            },
        },
    )


async def _runner_loop():
    """Main background loop. Wakes every 30s, runs due bots."""
    global _running
    log.info("bot_runner started")
    while _running:
        try:
            bots = await get_active_bots()
            now = datetime.utcnow()
            due = []
            for bot in bots:
                next_run = _parse_dt(bot.get("next_run_at"))
                if next_run is None or next_run <= now:
                    due.append(bot)

            if due:
                log.info(f"running {len(due)} due bot(s)")
                # Process bots in parallel — bots from different users don't share resources
                await asyncio.gather(*[_process_bot(b) for b in due], return_exceptions=True)
        except asyncio.CancelledError:
            break
        except Exception as e:
            log.exception(f"bot_runner loop error: {e}")

        try:
            await asyncio.sleep(30)
        except asyncio.CancelledError:
            break
    log.info("bot_runner stopped")


async def start_runner():
    """Start the runner if not already running."""
    global _running, _task
    if _running:
        return {"status": "already_running"}
    _running = True
    _task = asyncio.create_task(_runner_loop())
    return {"status": "started"}


async def stop_runner():
    global _running, _task
    _running = False
    if _task:
        _task.cancel()
        _task = None
    return {"status": "stopped"}


def is_running() -> bool:
    return _running
