"""
Bot Runner.

Background asyncio task that runs enabled normal bots concurrently, while
respecting high-impact news pauses. Emergency macro bots are handled by
emergency_macro_runner.
"""
import asyncio
from datetime import datetime, timedelta
from typing import Optional, Tuple

import pandas as pd

from database import db
from services.logger import child
from services.bots import get_active_bots, record_execution, SCHEDULES
from services import data_freshness
from services.strategies import STRATEGIES
from services.custom_strategy import run_custom_strategy
from services.backtest_engine import fetch_history
from services.adaptive_strategy_selector import select_strategy
from services.news_guard import should_pause_for_news
from services.signal_confidence import calibrate_signal_confidence

log = child("bot_runner")

_running = False
_task: Optional[asyncio.Task] = None
_concurrency = asyncio.Semaphore(8)

TIMEFRAME_BY_SCHEDULE = {"1m": "1m", "5m": "5m", "15m": "15m", "30m": "30m", "1h": "1h", "4h": "4h", "1d": "1d"}
LOOKBACK_BY_TIMEFRAME = {"1m": timedelta(days=7), "5m": timedelta(days=30), "15m": timedelta(days=45), "30m": timedelta(days=60), "1h": timedelta(days=90), "4h": timedelta(days=180), "1d": timedelta(days=365)}
MIN_BARS_BY_TIMEFRAME = {"1m": 80, "5m": 80, "15m": 80, "30m": 80, "1h": 80, "4h": 80, "1d": 30}
WINDOW_BARS_BY_TIMEFRAME = {"1m": 200, "5m": 200, "15m": 200, "30m": 200, "1h": 200, "4h": 200, "1d": 120}


def _parse_dt(s: Optional[str]) -> Optional[datetime]:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s)
    except Exception:
        return None


def _timeframe_for_bot(bot: dict) -> str:
    return TIMEFRAME_BY_SCHEDULE.get(bot.get("schedule", "1h"), "1h")


async def _load_user_strategy(user_id: str, strategy_id: str) -> Optional[dict]:
    from bson import ObjectId
    try:
        oid = ObjectId(strategy_id)
    except Exception:
        return None
    return await db["user_strategies"].find_one({"_id": oid, "user_id": user_id})


async def _fetch_strategy_history(ticker: str, asset_type: str, timeframe: str) -> Optional[pd.DataFrame]:
    lookback = LOOKBACK_BY_TIMEFRAME.get(timeframe, LOOKBACK_BY_TIMEFRAME["1h"])
    end_dt = datetime.utcnow()
    start_dt = end_dt - lookback
    return await fetch_history(ticker, asset_type, start_dt.strftime("%Y-%m-%d"), end_dt.strftime("%Y-%m-%d"), timeframe)


def _detect_local_regime(window: pd.DataFrame) -> Tuple[str, float]:
    try:
        if window is None or len(window) < 50:
            return "RANGING", 30.0
        close = window["close"].astype(float)
        high = window["high"].astype(float)
        low = window["low"].astype(float)
        ret = close.pct_change().dropna()
        recent_ret = float(ret.iloc[-20:].mean()) if len(ret) >= 20 else float(ret.mean())
        recent_vol = float(ret.iloc[-20:].std()) if len(ret) >= 20 else float(ret.std())
        atr_pct = float(((high - low).rolling(14).mean().iloc[-1] / close.iloc[-1]) * 100)
        ema_fast = close.ewm(span=12, adjust=False).mean().iloc[-1]
        ema_slow = close.ewm(span=26, adjust=False).mean().iloc[-1]
        trend_strength = abs(ema_fast - ema_slow) / close.iloc[-1] * 100
        if atr_pct > 1.8 and trend_strength > 0.25:
            return "VOLATILE", round(min(90.0, 55.0 + atr_pct * 8), 1)
        if trend_strength > 0.35 and recent_ret > recent_vol * 0.25:
            return "TRENDING_BULL", round(min(90.0, 55.0 + trend_strength * 30), 1)
        if trend_strength > 0.35 and recent_ret < -recent_vol * 0.25:
            return "TRENDING_BEAR", round(min(90.0, 55.0 + trend_strength * 30), 1)
        if atr_pct < 0.35 and trend_strength < 0.15:
            return "QUIET", 55.0
        return "RANGING", 55.0
    except Exception as e:
        log.debug(f"local regime detection failed: {e}")
        return "RANGING", 30.0


async def _generate_signal(strategy_type: str, strategy_id: str, user_id: str, ticker: str, asset_type: str, timeframe: str) -> Optional[dict]:
    try:
        df = await _fetch_strategy_history(ticker, asset_type, timeframe)
    except Exception as e:
        log.warning(f"fetch_history failed for {ticker} {timeframe}: {e}")
        return None
    min_bars = MIN_BARS_BY_TIMEFRAME.get(timeframe, 80)
    if df is None or len(df) < min_bars:
        got = 0 if df is None else len(df)
        return {"signal": "HOLD", "confidence": 0, "reason": f"insufficient {timeframe} history ({got}/{min_bars} bars)"}
    window = df.iloc[-WINDOW_BARS_BY_TIMEFRAME.get(timeframe, 200):]
    regime, regime_confidence = _detect_local_regime(window)
    effective_strategy_id = strategy_id
    selector_decision = None
    if strategy_type == "builtin":
        try:
            selector_decision = await select_strategy(user_id=user_id, configured_strategy=strategy_id, ticker=ticker, timeframe=timeframe, regime=regime, allow_auto_switch=True, allow_no_trade=True)
            if not selector_decision.get("allow_trade", True):
                return {"signal": "HOLD", "confidence": 0, "reason": selector_decision.get("reason", "adaptive selector blocked trade"), "timeframe": timeframe, "bars": len(window), "regime": regime, "regime_confidence": regime_confidence, "selector": selector_decision}
            effective_strategy_id = selector_decision.get("selected_strategy") or strategy_id
        except Exception as e:
            log.warning(f"adaptive selector failed for {ticker} {timeframe}: {e}")
    try:
        if strategy_type == "builtin":
            fn = STRATEGIES.get(effective_strategy_id)
            if not fn:
                return {"signal": "HOLD", "confidence": 0, "reason": f"unknown strategy {effective_strategy_id}"}
            sig = fn(window)
        else:
            strat_def = await _load_user_strategy(user_id, strategy_id)
            if not strat_def:
                return {"signal": "HOLD", "confidence": 0, "reason": "user strategy missing"}
            sig = run_custom_strategy(strat_def, window)
        if isinstance(sig, dict):
            sig.setdefault("timeframe", timeframe)
            sig.setdefault("bars", len(window))
            sig.setdefault("regime", regime)
            sig.setdefault("regime_confidence", regime_confidence)
            sig.setdefault("strategy_used", effective_strategy_id)
            if selector_decision:
                sig.setdefault("selector", selector_decision)
                if selector_decision.get("action") == "auto_switch":
                    sig["reason"] = f"adaptive switch {strategy_id} → {effective_strategy_id}; {sig.get('reason', '')}".strip()
        return sig
    except Exception as e:
        log.exception(f"signal generation failed for bot strategy {effective_strategy_id} on {ticker} {timeframe}: {e}")
        return None


async def _calc_position_size(user_id: str, bot: dict, price: float) -> float:
    from services import risk_engine
    equity = await risk_engine.get_account_equity(user_id)
    mode = bot.get("sizing_mode", "fixed_pct")
    sizing_pct = float(bot.get("sizing_pct", 1.0))
    target_dollars = equity * (sizing_pct / 100)
    limits = await risk_engine.get_limits(user_id) or {}
    max_pos_pct = float(limits.get("max_position_size_pct", 100))
    target_dollars = min(target_dollars, equity * (max_pos_pct / 100))
    if mode == "kelly":
        from services import signal_tracker
        stats = await signal_tracker.get_stats(user_id, "strategy")
        bot_stats = next((s for s in stats if s["key"] == bot.get("strategy_id")), None)
        if bot_stats and bot_stats["total"] >= 5:
            w = bot_stats["win_rate"] / 100
            kelly_frac = max(0.0, min(0.25, w - (1 - w)))
        else:
            kelly_frac = 0.02
        return (equity * kelly_frac) / price if price > 0 else 0
    return target_dollars / price if price > 0 else 0


async def _ensure_price(ticker: str, asset_type: str, timeframe: str) -> Optional[dict]:
    cached = data_freshness.get_price(ticker)
    if cached and not cached.get("expired"):
        return cached
    try:
        price_tf = timeframe if timeframe in TIMEFRAME_BY_SCHEDULE.values() else "1d"
        end_dt = datetime.utcnow()
        start_dt = end_dt - min(LOOKBACK_BY_TIMEFRAME.get(price_tf, timedelta(days=5)), timedelta(days=7))
        df_tail = await fetch_history(ticker, asset_type, start_dt.strftime("%Y-%m-%d"), end_dt.strftime("%Y-%m-%d"), price_tf)
        if df_tail is not None and len(df_tail):
            price = float(df_tail["close"].iloc[-1])
            data_freshness.set_price(ticker, price, ttl_sec=120, source=f"bot:{price_tf}")
            return {"price": price, "source": f"bot:{price_tf}"}
    except Exception as e:
        log.warning(f"price fetch failed for {ticker} {timeframe}: {e}")
    return None


async def _process_bot(bot: dict):
    async with _concurrency:
        await _process_bot_inner(bot)


async def _process_bot_inner(bot: dict):
    user_id = bot["user_id"]
    bot_id = bot["_id"]
    bot_name = bot.get("name", "?")
    timeframe = _timeframe_for_bot(bot)
    signals_fired = orders_placed = orders_rejected = 0
    from bson import ObjectId

    guard = await should_pause_for_news(bot)
    if guard.get("pause"):
        log.info(f"bot {bot_name} paused: {guard.get('reason')}")
        await record_execution(user_id, bot_id, "NEWS", "macro", "HOLD", 0, "skipped", reason=guard.get("reason"), order_result=guard)
        schedule_secs = SCHEDULES.get(bot.get("schedule", "1h"), 3600)
        now = datetime.utcnow()
        await db["bots"].update_one({"_id": ObjectId(bot_id)}, {"$set": {"last_run_at": now.isoformat(), "next_run_at": (now + timedelta(seconds=min(schedule_secs, 300))).isoformat(), "last_pause_reason": guard.get("reason")}, "$inc": {"stats.runs": 1, "stats.news_pauses": 1}})
        return

    if bot.get("bot_role") == "emergency_macro":
        return

    log.info(f"running bot {bot_name} ({bot_id}) for user {user_id} on {timeframe} candles")
    try:
        for item in bot["watchlist"]:
            ticker = item["ticker"].upper()
            asset_type = item.get("asset_type", "stock")
            sig = await _generate_signal(bot["strategy_type"], bot["strategy_id"], user_id, ticker, asset_type, timeframe)
            if not sig:
                await record_execution(user_id, bot_id, ticker, asset_type, "HOLD", 0, "skipped", reason="signal generation failed")
                continue
            try:
                sig = await calibrate_signal_confidence(user_id, ticker, asset_type, sig, bot=bot)
            except Exception as e:
                log.warning(f"confidence calibration failed for {ticker}: {e}")
            signal_str = sig.get("signal", "HOLD")
            confidence = float(sig.get("confidence", 0))
            signal_reason = sig.get("reason", "")
            regime = sig.get("regime", "unknown")
            strategy_used = sig.get("strategy_used", bot.get("strategy_id"))
            selector = sig.get("selector")
            calibration = sig.get("calibration")
            if signal_str == "HOLD" or ("BUY" not in signal_str and "SELL" not in signal_str):
                await record_execution(user_id, bot_id, ticker, asset_type, signal_str, confidence, "skipped", reason=signal_reason or f"HOLD signal on {timeframe} {regime}", order_result={"calibration": calibration} if calibration else None)
                continue
            if confidence < bot.get("min_confidence", 60):
                await record_execution(user_id, bot_id, ticker, asset_type, signal_str, confidence, "skipped", reason=f"below calibrated min_confidence ({confidence} < {bot['min_confidence']}) on {timeframe} {regime}", order_result={"calibration": calibration} if calibration else None)
                continue
            signals_fired += 1
            cached = await _ensure_price(ticker, asset_type, timeframe)
            if not cached:
                await record_execution(user_id, bot_id, ticker, asset_type, signal_str, confidence, "rejected", reason=f"no fresh price available for {timeframe}")
                orders_rejected += 1
                continue
            price = cached["price"]
            qty = await _calc_position_size(user_id, bot, price)
            if qty <= 0:
                await record_execution(user_id, bot_id, ticker, asset_type, signal_str, confidence, "rejected", reason="size = 0")
                orders_rejected += 1
                continue
            side = "buy" if "BUY" in signal_str else "sell"
            broker = bot.get("broker", "paper")
            try:
                if broker == "paper":
                    from services import paper_broker
                    result = await paper_broker.place_order(
                        user_id=user_id, ticker=ticker, side=side, qty=qty,
                        order_type="market", current_price=price, asset_type=asset_type,
                        skip_freshness=False,
                        strategy=strategy_used, timeframe=timeframe, regime=regime,
                    )
                else:
                    from services.order_router import submit_order
                    result = await submit_order(user_id=user_id, broker_id=broker, ticker=ticker, side=side, qty=qty, order_type="market", confirm_live=True)
            except Exception as e:
                log.exception(f"bot {bot_name} order failed for {ticker}: {e}")
                await record_execution(user_id, bot_id, ticker, asset_type, signal_str, confidence, "rejected", reason=f"order error: {e}")
                orders_rejected += 1
                continue
            status = result.get("status")
            result.setdefault("bot_context", {"timeframe": timeframe, "regime": regime, "strategy_used": strategy_used, "selector": selector, "calibration": calibration})
            if status in {"filled", "submitted"}:
                orders_placed += 1
                await record_execution(user_id, bot_id, ticker, asset_type, signal_str, confidence, "placed", order_result=result, reason=f"{timeframe} {regime} strategy={strategy_used} calibrated_conf={confidence}")
                log.info(f"bot {bot_name} placed {side} {qty:.4f} {ticker} @ {price:.2f} (calibrated sig {confidence}% {timeframe} {regime} {strategy_used})")
            else:
                orders_rejected += 1
                await record_execution(user_id, bot_id, ticker, asset_type, signal_str, confidence, "rejected", order_result=result, reason=result.get("reason") or result.get("message", "unknown"))
    except Exception as e:
        log.exception(f"bot {bot_name} processing crashed: {e}")
    finally:
        # Always advance next_run_at so a transient crash doesn't tight-loop the bot.
        schedule_secs = SCHEDULES.get(bot.get("schedule", "1h"), 3600)
        now = datetime.utcnow()
        try:
            await db["bots"].update_one(
                {"_id": ObjectId(bot_id)},
                {
                    "$set": {
                        "last_run_at": now.isoformat(),
                        "next_run_at": (now + timedelta(seconds=schedule_secs)).isoformat(),
                        "last_timeframe": timeframe,
                    },
                    "$inc": {
                        "stats.runs": 1,
                        "stats.signals_fired": signals_fired,
                        "stats.orders_placed": orders_placed,
                        "stats.orders_rejected": orders_rejected,
                    },
                },
            )
        except Exception as e:
            log.warning(f"bot {bot_name} schedule update failed: {e}")


async def _runner_loop():
    global _running
    log.info("bot_runner started")
    while _running:
        try:
            # Respect the frontend kill-switch for the normal bot fleet. If an
            # operator toggles this off in /api/runtime-controls the loop keeps
            # ticking but skips every cycle.
            from services.runtime_controls import is_normal_bots_enabled
            if not await is_normal_bots_enabled():
                await asyncio.sleep(15)
                continue
            bots = await get_active_bots()
            now = datetime.utcnow()
            due = [bot for bot in bots if (_parse_dt(bot.get("next_run_at")) is None or _parse_dt(bot.get("next_run_at")) <= now)]
            if due:
                log.info(f"running {len(due)} due bot(s)")
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
