# TradeAI Platform v6.0 — Autonomous Trading Bots

A self-learning trading platform where users build strategies in the UI and deploy them as autonomous bots that trade their accounts on schedule, with full risk controls.

## What's new in v6.0 — the autonomous layer

Strategies in the Strategy Lab were useful but had to be backtested manually. Now they can run by themselves.

### Trading Bots
A **bot** is a recipe:
- **Strategy** — any built-in (trend_follow, ensemble, …) OR any of your custom Strategy Lab strategies
- **Watchlist** — up to 20 tickers (stocks or crypto)
- **Schedule** — 1m, 5m, 15m, 30m, 1h, 4h, 1d
- **Broker** — paper, alpaca, binance, or oanda
- **Sizing** — fixed % per trade, Kelly (data-driven), or ATR-adjusted
- **Min confidence** — only fires orders ≥ this threshold

### Bot runner
A background asyncio task that:
- Wakes every 30 seconds
- Picks up every enabled bot whose `next_run_at` is due
- Runs its strategy across the watchlist
- Sends qualifying signals through the order router (which still enforces risk + idempotency + freshness)
- Records every execution (placed / skipped / rejected with reason)
- Updates bot stats: runs, signals_fired, orders_placed, orders_rejected

### Risk gating
A bot **cannot be enabled** until risk limits are configured. Once running:
- Kill switch blocks every bot order globally
- Daily loss limit blocks new entries
- Position-size cap shrinks bot sizing automatically
- Every order still hits the freshness gate and idempotency check

### Live trading
A bot can target paper or live. For live execution, ALL of these still apply (from v5.2):
- Broker connected with `paper_mode=False`
- `LIVE_TRADING_ENABLED=true` in `.env`
- Risk limits set and not breached
- Cached price < 60s old

### New tests (166 total, was 144)
- **16 bot tests**: CRUD + validation + scheduling + kill-switch gating + risk-limits gating + user isolation
- **4 new route auth checks**: confirms bot endpoints require authentication

## Version history

- **v6.0** — Autonomous Trading Bots: schedule + execute strategies, 22 new tests
- **v5.3** — Strategy Lab: user-defined strategies + sandbox + 39 security tests
- **v5.2** — Real broker execution (Alpaca/Binance/OANDA) + 73 tests
- **v5.1** — Auth audit, WebSocket auth, silent-catch cleanup
- **v5.0** — Production hardening: user scoping, risk engine, paper v2, charts

### Security & isolation
- **User scoping** — every record (trades, orders, positions, alerts, backtests, brokers) is tagged with `user_id`; users only see their own data, admins see all
- **JWT secret enforcement** — server logs a loud warning and rejects auth if `JWT_SECRET` is missing or < 32 chars
- **Hardened auth** — first registered user becomes admin; `/auth/me` validates token on app boot
- **Token validation on startup** — frontend hits `/auth/me` before rendering, so expired tokens log out cleanly

### Risk engine
- **Kill switch** — instantly blocks all new orders, user-scoped, surfaced in the SafetyBar
- **Daily loss limit** — stops new trades when day P&L crosses threshold
- **Max drawdown** — halts trading when equity drops X% from peak
- **Max open trades** — caps concurrent positions
- **Max position size %** — no single position larger than X% of equity
- **No defaults** — auto-trader won't start until risk limits are configured

### Paper trading v2
- Realistic fills with fees (bps), slippage (bps), spread (bps)
- Order types: market, limit, stop
- Tracks realized + unrealized P&L per position
- Position book with mark-to-market against live prices
- Order log with status (filled, open, cancelled, rejected)
- Goes through risk engine + idempotency check before every fill
- Stale-price gate (configurable max age, default 60s)

### Backtest v2
- Multi-strategy: trend-follow, mean-revert, breakout, ensemble
- Compare mode runs all strategies in parallel
- Equity curve, drawdown curve, full trade log
- Walk-forward, bar-by-bar, no lookahead
- Per-strategy attribution

### Signal performance tracking
- Logs every signal with metadata (strategy, timeframe, regime, ticker)
- Aggregates win rate grouped by any dimension
- Derives strategy weights from rolling performance for auto-adjustment

### Frontend polish
- Shared UI component library (`components/ui/`) — Card, Button, Input, Toggle, Metric, Badge, Loading, Empty, ErrorState
- **5 chart types** — LineChart (equity), DrawdownChart (underwater), BarChart (P&L history), DonutChart (allocation), Heatmap (signal accuracy)
- **SafetyBar** — global banner showing mode/equity/daily loss/drawdown/open trades + kill switch
- Mobile-responsive sidebar (slide-in on < 800px)
- Loading and error states everywhere

### Tests
- **27 tests** passing — auth, risk engine, paper broker, backtest engine, signal tracker
- mongomock-motor for in-memory DB (no Atlas pollution)

## Setup

### Backend

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# Generate a JWT secret (REQUIRED)
python -c "import secrets; print(secrets.token_urlsafe(48))"

# Copy template and edit
cp .env.example .env
# Paste the secret into JWT_SECRET, set MONGO_URL, optionally add GEMINI_API_KEY

uvicorn main:app --reload
```

### Frontend

```bash
cd frontend
npm install
npm run dev   # http://localhost:5173
```

### Tests

```bash
cd backend
JWT_SECRET="test_$(python3 -c 'import secrets; print(secrets.token_urlsafe(48))')" pytest tests/
```

## First-run flow

1. Register the first account → becomes admin
2. Go to **Settings** → set all 4 risk limits (auto-trader is blocked until you do)
3. Go to **Portfolio** → place a paper market order to seed the equity curve
4. Go to **Backtest** → try the "Compare All Strategies" mode
5. Watch the **SafetyBar** at the top — it refreshes every 15s with equity, daily P&L, drawdown, and the kill switch

## API reference

- `/api/auth/{register,login,refresh,me}` — public; `/me` validates token
- `/api/risk/{status,limits,kill-switch,check}` — user-scoped
- `/api/paper/{account,summary,order,orders,positions,reset}` — user-scoped
- `/api/backtest/{run,compare,history,strategies}` — user-scoped
- `/api/signal-perf/{recent,stats/{group_by},weights}` — user-scoped
- `/api/signals/{ticker}` — user-scoped, logs to signal tracker
- `/api/portfolio`, `/api/alerts`, `/api/broker`, `/api/reward` — user-scoped
- `/api/market`, `/api/sentiment` — public (market data is not personal)

Full Swagger UI: http://localhost:8000/docs

## Architecture notes

- **Logger**: `services/logger.py` — rotating file + console, used by every service via `child('name')`
- **No more `except: pass`** — all silent failures replaced with `log.debug()`
- **Idempotency**: `services/order_idempotency.py` — hashes (user, ticker, side, qty, minute_bucket) to block duplicates
- **Freshness**: `services/data_freshness.py` — in-memory price cache with TTL, rejects trades on stale data
- **Strategy weights**: signal performance feeds back into strategy weighting automatically (≥5 resolved signals required)

## Version history

- **v5.2** — Real broker execution + 100 tests (broker adapters, order router, E2E auth coverage)
- **v5.1** — SafetyBar fix, full route auth audit, WebSocket auth, silent-catch cleanup
- **v5.0** — Production hardening: user scoping, risk engine, paper v2, backtest v2, signal tracking, charts, mobile, tests
- **v4.3** — Self-learning: meta-learner + RL + WFO + tuner + defensive + VP + microstructure + LLM sentiment
- **v4.2** — Quant pipeline: Kelly + MC + MTF + Bayesian + Regime
- **v4.1** — Auto-trader + WebSocket
- **v4.0** — Initial release

## Roadmap

- Live broker order routing behind `LIVE_TRADING_ENABLED=true` + explicit confirmation flag (currently gated as paper-equivalent)
- Redis-backed price cache (currently in-memory)
- WebSocket auth (currently public on `/ws/prices`)
- Per-user broker order tests for Alpaca/Binance/OANDA
