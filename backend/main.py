"""
TradeAI Platform — main FastAPI app.

v6.3 — ASI-Evolve + global logs mounted.
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
    asi as asi_router, logs as logs_router, diagnostics as diagnostics_router,
    emergency_bot as emergency_bot_router, trades as trades_router,
    monitoring as monitoring_router, learners as learners_router,
)

@asynccontextmanager
async def lifespan(app: FastAPI):
    secret = os.getenv("JWT_SECRET", "")
    if not secret or secret in ("tradeai_secret_change_me", "change_me", "secret") or len(secret) < 32:
        log.error("=" * 70); log.error("JWT_SECRET is missing or insecure!"); log.error("Generate one: python -c 'import secrets; print(secrets.token_urlsafe(48))'"); log.error("=" * 70)
    else: log.info("JWT_SECRET present and valid length")
    for label, starter in [
        ("DB indexes", "database.create_indexes"), ("Signal resolver", "services.signal_resolver.start_resolver"), ("Auto signal scanner", "services.auto_signal_scanner.start_auto_signal_scanner"), ("Regime scheduler", None), ("WFO scheduler", "services.wfo_service.start_wfo_scheduler"), ("Hyper tuner", "services.hyper_tuner.start_tuning_scheduler"), ("Economic event scheduler", None), ("Emergency macro runner", "services.emergency_macro_runner.start_emergency_macro_runner"), ("Bot runner", "services.bot_runner.start_runner")]:
        try:
            if label == "Regime scheduler":
                from services.strategy_manager import start_regime_scheduler; await start_regime_scheduler([{"ticker":"BTC","type":"crypto"},{"ticker":"ETH","type":"crypto"},{"ticker":"EUR_USD","type":"forex"}], True)
            elif label == "Economic event scheduler":
                from services.economic_event_engine import start_economic_event_scheduler; await start_economic_event_scheduler(interval_sec=int(os.getenv("ECONOMIC_EVENT_SCAN_INTERVAL_SEC", "30")))
            else:
                mod_name, fn_name = starter.rsplit(".", 1); import importlib; fn = getattr(importlib.import_module(mod_name), fn_name); res = fn();
                if asyncio.iscoroutine(res): await res
            log.info(f"{label} started/ready")
        except Exception as e: log.exception(f"{label} init failed: {e}")
    try:
        from services.auto_trader import get_config, start_scheduler
        c = await get_config()
        if c.get("enabled"): await start_scheduler(); log.info("Auto-trader resumed")
    except Exception as e: log.exception(f"Auto-trader init failed: {e}")
    from websocket_manager import broadcast_loop
    task = asyncio.create_task(broadcast_loop()); log.info("TradeAI v6.3 ready")
    try: yield
    finally:
        task.cancel()
        try: await task
        except (asyncio.CancelledError, Exception): pass
        for stopper in ["services.bot_runner.stop_runner","services.auto_trader.stop_scheduler","services.signal_resolver.stop_resolver","services.auto_signal_scanner.stop_auto_signal_scanner"]:
            try:
                mod_name, fn_name = stopper.rsplit(".", 1); import importlib; fn = getattr(importlib.import_module(mod_name), fn_name, None); res = fn() if fn else None
                if asyncio.iscoroutine(res): await res
            except Exception as e: log.debug(f"shutdown hook {stopper} failed: {e}")
        try:
            from database import client as db_client; db_client.close()
        except Exception as e: log.debug(f"DB client close failed: {e}")

app = FastAPI(title="TradeAI Platform API", version="6.3.0", lifespan=lifespan)
_cors_raw = os.getenv("CORS_ORIGINS", ""); _cors_origins = [o.strip() for o in _cors_raw.split(",") if o.strip()]; _environment = os.getenv("ENVIRONMENT", "development").lower()
if "*" in _cors_origins:
    if _environment == "production": raise RuntimeError("CORS_ORIGINS='*' is not allowed in production with credentials")
    app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=False, allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE", "OPTIONS"], allow_headers=["Authorization", "Content-Type", "X-Requested-With"])
elif _cors_origins:
    app.add_middleware(CORSMiddleware, allow_origins=_cors_origins, allow_credentials=True, allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE", "OPTIONS"], allow_headers=["Authorization", "Content-Type", "X-Requested-With"])
else:
    if _environment == "production": raise RuntimeError("CORS_ORIGINS must be set in production")
    app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"], allow_credentials=True, allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE", "OPTIONS"], allow_headers=["Authorization", "Content-Type", "X-Requested-With"])

for r,p,t in [(auth.router,"/api/auth","Auth"),(market.router,"/api/market","Market"),(sentiment.router,"/api/sentiment","Sentiment"),(signals.router,"/api/signals","Signals"),(auto_signals_router.router,"/api/auto-signals","Auto Signals"),(portfolio.router,"/api/portfolio","Portfolio"),(alerts.router,"/api/alerts","Alerts"),(ai_research.router,"/api/ai","AI"),(backtest.router,"/api/backtest","Backtest"),(reward.router,"/api/reward","Rewards"),(auto_trader.router,"/api/autotrader","AutoTrader"),(trades_router.router,"/api/trades","Trades"),(strategy.router,"/api/strategy","Strategy"),(quant.router,"/api/quant","Quant"),(resolver.router,"/api/resolver","Resolver"),(broker.router,"/api/broker","Broker"),(learning.router,"/api/learning","Learning"),(advanced.router,"/api/advanced","Advanced"),(risk.router,"/api/risk","Risk"),(paper.router,"/api/paper","Paper Trading"),(signal_perf.router,"/api/signal-perf","Signal Performance"),(strategy_lab.router,"/api/strategy-lab","Strategy Lab"),(bots_router.router,"/api/bots","Bots"),(macro.router,"/api/macro","Macro"),(runtime_controls_router.router,"/api/runtime-controls","Runtime Controls"),(context_router.router,"/api/context","Market Context"),(calendar_router.router,"/api/calendar","Economic Calendar"),(asi_router.router,"/api/asi","ASI Evolve"),(logs_router.router,"/api/logs","Logs"),(diagnostics_router.router,"/api/diagnostics","Diagnostics"),(emergency_bot_router.router,"/api/emergency-bot","Emergency Bot"),(monitoring_router.router,"/api/monitoring","Monitoring"),(learners_router.router,"/api/learners","Learners")]: app.include_router(r, prefix=p, tags=[t])

from websocket_manager import manager
UNSAFE_SECRETS = {"tradeai_secret_change_me", "change_me", "secret", "test"}
def _ws_authenticate(websocket: WebSocket) -> str:
    import jwt as _jwt
    token = websocket.query_params.get("token")
    if not token: return None
    secret = os.getenv("JWT_SECRET", "")
    if not secret or len(secret) < 32 or secret in UNSAFE_SECRETS: return None
    try:
        payload = _jwt.decode(token, secret, algorithms=["HS256"])
        return payload.get("sub") if payload.get("type") == "access" else None
    except Exception: return None
@app.websocket("/ws/prices")
async def ws(websocket: WebSocket):
    user_id = _ws_authenticate(websocket)
    if not user_id: await websocket.close(code=4401); return
    await websocket.accept(); manager.register_authenticated(websocket, user_id)
    try:
        while True:
            d = await websocket.receive_json(); action = d.get("action", ""); tickers = d.get("tickers", [])
            if action == "subscribe": manager.subscribe(websocket, tickers); await manager.send(websocket, {"type":"subscribed","tickers":tickers})
            elif action == "unsubscribe": manager.unsubscribe(websocket, tickers)
    except (WebSocketDisconnect, Exception): manager.disconnect(websocket)
@app.get("/")
def root():
    return {"status":"TradeAI Platform v6.3 🚀","docs":"/docs","auto_signal_scanner":True,"asi_evolve":True,"optuna_backtest":True,"global_logs":True,"diagnostics":True,"emergency_bot":True,"monitoring":True,"features":["user-scoping","risk-engine","paper-broker-v2","multi-strategy-backtest","optuna-optimization","asi-evolve-strategy-generation","tradingview-style-local-indicators","shared-cache","websocket-prices","environment-diagnostics","macro-emergency-bot","universal-trade-inspector","system-monitoring"]}
