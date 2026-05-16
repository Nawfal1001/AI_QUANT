"""
TradeAI Platform — main FastAPI app.

v6.1 — Connected macro/emergency system:
- Normal bot runner with high-impact news guard
- Economic event scheduler
- Emergency macro runner
- Macro API routes for frontend monitoring/control
"""
import asyncio
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from services.logger import log
from routers import (
    auth, market, signals, portfolio, alerts, ai_research, backtest, reward,
    sentiment, auto_trader, strategy, quant, resolver, broker, learning, advanced,
    risk, paper, signal_perf, strategy_lab, bots as bots_router, macro,
    runtime_controls as runtime_controls_router, context as context_router,
    auto_signals as auto_signals_router, calendar as calendar_router,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    secret = os.getenv("JWT_SECRET", "")
    if not secret or secret in ("tradeai_secret_change_me", "change_me", "secret") or len(secret) < 32:
        log.error("=" * 70)
        log.error("JWT_SECRET is missing or insecure!")
        log.error("Generate one: python -c 'import secrets; print(secrets.token_urlsafe(48))'")
        log.error("Add to .env: JWT_SECRET=<that_value>")
        log.error("All auth attempts will fail until this is fixed.")
        log.error("=" * 70)
    else:
        log.info("JWT_SECRET present and valid length")

    try:
        from database import create_indexes
        await create_indexes()
        log.info("DB indexes ready")
    except Exception as e:
        log.exception(f"DB init failed: {e}")

    try:
        from services.signal_resolver import start_resolver
        await start_resolver()
        log.info("Signal resolver started")
    except Exception as e:
        log.exception(f"Signal resolver init failed: {e}")

    try:
        from services.auto_trader import get_config, start_scheduler
        c = await get_config()
        if c.get("enabled"):
            await start_scheduler()
            log.info("Auto-trader resumed")
    except Exception as e:
        log.exception(f"Auto-trader init failed: {e}")

    try:
        from services.strategy_manager import start_regime_scheduler
        wl = [{"ticker": "AAPL", "type": "stock"}, {"ticker": "BTC", "type": "crypto"}, {"ticker": "ETH", "type": "crypto"}]
        await start_regime_scheduler(wl, True)
        log.info("Regime scheduler started")
    except Exception as e:
        log.exception(f"Regime scheduler init failed: {e}")

    try:
        from services.wfo_service import start_wfo_scheduler
        await start_wfo_scheduler()
        log.info("WFO scheduler started (weekly)")
    except Exception as e:
        log.exception(f"WFO init failed: {e}")

    try:
        from services.hyper_tuner import start_tuning_scheduler
        await start_tuning_scheduler()
        log.info("Hyper tuner started (weekly)")
    except Exception as e:
        log.exception(f"Hyper tuner init failed: {e}")

    try:
        from services.economic_event_engine import start_economic_event_scheduler
        await start_economic_event_scheduler(interval_sec=int(os.getenv("ECONOMIC_EVENT_SCAN_INTERVAL_SEC", "30")))
        # Auto signal scanner — runs the universe→signals pipeline in the background
        # so the Dashboard / Auto-Signals page always has fresh actionable picks.
        from services.auto_signal_scanner import start_auto_signal_scanner
        await start_auto_signal_scanner()
        log.info("Auto signal scanner started")
        log.info("Economic event scheduler started")
    except Exception as e:
        log.exception(f"Economic event scheduler init failed: {e}")

    try:
        from services.emergency_macro_runner import start_emergency_macro_runner
        await start_emergency_macro_runner()
        log.info("Emergency macro runner started")
    except Exception as e:
        log.exception(f"Emergency macro runner init failed: {e}")

    try:
        from services.bot_runner import start_runner
        await start_runner()
        log.info("Bot runner started")
    except Exception as e:
        log.exception(f"Bot runner init failed: {e}")

    from websocket_manager import broadcast_loop
    task = asyncio.create_task(broadcast_loop())
    log.info("TradeAI v6.1 ready (macro emergency system connected)")
    try:
        yield
    finally:
        # Cancel WS broadcast task
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):
            pass
        # Stop schedulers that expose a stop_*/cancel hook
        for stopper in [
            "services.bot_runner.stop_runner",
            "services.auto_trader.stop_scheduler",
            "services.signal_resolver.stop_resolver",
            "services.auto_signal_scanner.stop_auto_signal_scanner",
        ]:
            try:
                mod_name, fn_name = stopper.rsplit(".", 1)
                import importlib
                mod = importlib.import_module(mod_name)
                fn = getattr(mod, fn_name, None)
                if fn:
                    res = fn()
                    if asyncio.iscoroutine(res):
                        await res
            except Exception as e:
                log.debug(f"shutdown hook {stopper} failed: {e}")
        # Close DB client
        try:
            from database import client as db_client
            db_client.close()
        except Exception as e:
            log.debug(f"DB client close failed: {e}")


app = FastAPI(title="TradeAI Platform API", version="6.1.0", lifespan=lifespan)

_cors_raw = os.getenv("CORS_ORIGINS", "")
_cors_origins = [o.strip() for o in _cors_raw.split(",") if o.strip()]
_environment = os.getenv("ENVIRONMENT", "development").lower()
if "*" in _cors_origins:
    if _environment == "production":
        raise RuntimeError("CORS_ORIGINS='*' is not allowed in production with credentials")
    log.warning("CORS_ORIGINS contains '*' — disabling allow_credentials per browser spec")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-Requested-With"],
    )
elif _cors_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-Requested-With"],
    )
else:
    if _environment == "production":
        raise RuntimeError("CORS_ORIGINS must be set in production (comma-separated origin list)")
    log.warning("CORS_ORIGINS unset — defaulting to http://localhost:5173 for dev")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-Requested-With"],
    )

app.include_router(auth.router,        prefix="/api/auth",        tags=["Auth"])
app.include_router(market.router,      prefix="/api/market",      tags=["Market"])
app.include_router(sentiment.router,   prefix="/api/sentiment",   tags=["Sentiment"])
app.include_router(signals.router,     prefix="/api/signals",     tags=["Signals"])
app.include_router(portfolio.router,   prefix="/api/portfolio",   tags=["Portfolio"])
app.include_router(alerts.router,      prefix="/api/alerts",      tags=["Alerts"])
app.include_router(ai_research.router, prefix="/api/ai",          tags=["AI"])
app.include_router(backtest.router,    prefix="/api/backtest",    tags=["Backtest"])
app.include_router(reward.router,      prefix="/api/reward",      tags=["Rewards"])
app.include_router(auto_trader.router, prefix="/api/autotrader",  tags=["AutoTrader"])
app.include_router(strategy.router,    prefix="/api/strategy",    tags=["Strategy"])
app.include_router(quant.router,       prefix="/api/quant",       tags=["Quant"])
app.include_router(resolver.router,    prefix="/api/resolver",    tags=["Resolver"])
app.include_router(broker.router,      prefix="/api/broker",      tags=["Broker"])
app.include_router(learning.router,    prefix="/api/learning",    tags=["Learning"])
app.include_router(advanced.router,    prefix="/api/advanced",    tags=["Advanced"])
app.include_router(risk.router,        prefix="/api/risk",        tags=["Risk"])
app.include_router(paper.router,       prefix="/api/paper",       tags=["Paper Trading"])
app.include_router(signal_perf.router, prefix="/api/signal-perf", tags=["Signal Performance"])
app.include_router(strategy_lab.router, prefix="/api/strategy-lab", tags=["Strategy Lab"])
app.include_router(bots_router.router, prefix="/api/bots", tags=["Bots"])
app.include_router(macro.router, prefix="/api/macro", tags=["Macro"])
app.include_router(runtime_controls_router.router, prefix="/api/runtime-controls", tags=["Runtime Controls"])
app.include_router(context_router.router, prefix="/api/context", tags=["Market Context"])
app.include_router(auto_signals_router.router, prefix="/api/auto-signals", tags=["Auto Signals"])
app.include_router(calendar_router.router, prefix="/api/calendar", tags=["Economic Calendar"])

from websocket_manager import manager


UNSAFE_SECRETS = {"tradeai_secret_change_me", "change_me", "secret", "test"}


def _ws_authenticate(websocket: WebSocket) -> str:
    import jwt as _jwt
    token = websocket.query_params.get("token")
    if not token:
        return None
    secret = os.getenv("JWT_SECRET", "")
    if not secret or len(secret) < 32 or secret in UNSAFE_SECRETS:
        return None
    try:
        payload = _jwt.decode(token, secret, algorithms=["HS256"])
        if payload.get("type") != "access":
            return None
        return payload.get("sub")
    except Exception:
        return None


@app.websocket("/ws/prices")
async def ws(websocket: WebSocket):
    # Authenticate BEFORE accepting the WS handshake so unauth clients cannot
    # even open a connection.
    user_id = _ws_authenticate(websocket)
    if not user_id:
        await websocket.close(code=4401)
        return
    await websocket.accept()
    manager.register_authenticated(websocket, user_id)
    try:
        while True:
            d = await websocket.receive_json()
            action = d.get("action", "")
            tickers = d.get("tickers", [])
            if action == "subscribe":
                manager.subscribe(websocket, tickers)
                await manager.send(websocket, {"type": "subscribed", "tickers": tickers})
            elif action == "unsubscribe":
                manager.unsubscribe(websocket, tickers)
    except (WebSocketDisconnect, Exception):
        manager.disconnect(websocket)


@app.get("/")
def root():
    return {
        "status": "TradeAI Platform v6.1 🚀",
        "docs": "/docs",
        "self_learning": True,
        "production_hardening": True,
        "macro_emergency_system": True,
        "features": [
            "user-scoping", "risk-engine", "kill-switch", "paper-broker-v2",
            "multi-strategy-backtest", "signal-performance-tracking",
            "adaptive-strategy-selector", "dynamic-watchlists", "broker-aware-scanner",
            "macro-report-analysis", "economic-event-engine", "news-guard",
            "emergency-macro-runner", "shared-cache", "websocket-prices",
        ],
    }
