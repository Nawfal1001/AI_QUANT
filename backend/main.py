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
    log.info("TradeAI v6.1 ready 🚀 (macro emergency system connected)")
    yield
    task.cancel()


app = FastAPI(title="TradeAI Platform API", version="6.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("CORS_ORIGINS", "*").split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
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

from websocket_manager import manager


async def _ws_authenticate(websocket: WebSocket) -> str:
    import jwt as _jwt
    token = websocket.query_params.get("token")
    if not token:
        return None
    secret = os.getenv("JWT_SECRET", "")
    if not secret or len(secret) < 32:
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
    await websocket.accept()
    user_id = await _ws_authenticate(websocket)
    if not user_id:
        await websocket.send_json({"type": "error", "code": 4401, "message": "Auth required"})
        await websocket.close(code=4401)
        return
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
