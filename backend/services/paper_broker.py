"""
Paper Trading Broker.

Per-user simulated trading with realistic execution:
- Market orders fill at next price ± slippage ± spread, commission deducted
- Limit orders queue and fill if price touches
- Stop orders trigger on adverse move
- Tracks realized + unrealized PnL, order status, position book
- Goes through risk_engine.check_order() and order_idempotency before filling

DB collections (all scoped by user_id):
- paper_accounts   : starting capital, current cash, equity
- paper_orders     : open/filled/cancelled/rejected orders
- paper_positions  : open positions
- trades           : closed trades (shared with risk engine)
"""
from datetime import datetime
from typing import Optional

from database import db
from services.logger import child
from services import risk_engine, order_idempotency, data_freshness

log = child("paper")

col_accounts = db["paper_accounts"]
col_orders = db["paper_orders"]
col_positions = db["paper_positions"]
col_trades = db["trades"]

# Default execution costs (basis points)
DEFAULT_FEE_BPS = 5      # 0.05% commission
DEFAULT_SLIPPAGE_BPS = 3
DEFAULT_SPREAD_BPS = 2


async def get_account(user_id: str) -> dict:
    """Get or create the paper account."""
    acct = await col_accounts.find_one({"user_id": user_id})
    if not acct:
        acct = {
            "user_id": user_id,
            "starting_capital": 10000.0,
            "cash": 10000.0,
            "equity": 10000.0,
            "created_at": datetime.utcnow().isoformat(),
        }
        await col_accounts.insert_one(acct)
        log.info(f"created paper account for {user_id}")
    acct.pop("_id", None)
    return acct


async def reset_account(user_id: str, starting_capital: float = 10000) -> dict:
    """Wipe paper history. Keeps risk_limits."""
    await col_accounts.delete_many({"user_id": user_id})
    await col_orders.delete_many({"user_id": user_id})
    await col_positions.delete_many({"user_id": user_id})
    await col_trades.delete_many({"user_id": user_id, "broker": "paper"})
    new = {
        "user_id": user_id,
        "starting_capital": float(starting_capital),
        "cash": float(starting_capital),
        "equity": float(starting_capital),
        "created_at": datetime.utcnow().isoformat(),
    }
    await col_accounts.insert_one(new)
    log.info(f"reset paper account for {user_id} to ${starting_capital}")
    return {"status": "reset", "starting_capital": starting_capital}


def _apply_costs(price: float, side: str, fee_bps: float, slip_bps: float, spread_bps: float) -> float:
    cost_pct = (slip_bps + spread_bps) / 10000
    fee_pct = fee_bps / 10000
    if side.lower() == "buy":
        exec_price = price * (1 + cost_pct)
        return exec_price * (1 + fee_pct)
    else:
        exec_price = price * (1 - cost_pct)
        return exec_price * (1 - fee_pct)


async def place_order(
    user_id: str,
    ticker: str,
    side: str,
    qty: float,
    order_type: str = "market",
    limit_price: float = None,
    stop_price: float = None,
    current_price: float = None,
    asset_type: str = "stock",
    skip_freshness: bool = False,
    fee_bps: float = DEFAULT_FEE_BPS,
    slip_bps: float = DEFAULT_SLIPPAGE_BPS,
    spread_bps: float = DEFAULT_SPREAD_BPS,
    strategy: str = None,
    timeframe: str = None,
    regime: str = None,
) -> dict:
    """Place a paper order. Runs risk, freshness, idempotency checks."""

    side = side.lower()
    if side not in ("buy", "sell"):
        return {"status": "rejected", "reason": f"Invalid side: {side}"}
    if qty <= 0:
        return {"status": "rejected", "reason": "Quantity must be positive"}

    # Freshness check
    if not skip_freshness and current_price is None:
        freshness = data_freshness.check_freshness(ticker, max_age_sec=60)
        if not freshness["fresh"]:
            log.warning(f"order rejected for {user_id} {ticker}: {freshness['reason']}")
            return {"status": "rejected", "reason": freshness["reason"]}
        current_price = freshness["price"]
    elif current_price is None:
        return {"status": "rejected", "reason": "No current price available"}

    # Idempotency check
    idem = order_idempotency.check_and_record(user_id, ticker, side, qty)
    if not idem["unique"]:
        return {"status": "rejected", "reason": idem["reason"]}

    # Risk check (size = qty * price)
    position_size = qty * current_price
    risk = await risk_engine.check_order(user_id, position_size, ticker)
    if not risk["allowed"]:
        order_idempotency.release(idem["key"])
        log.warning(f"order rejected for {user_id} {ticker}: {risk['reason']}")
        return {"status": "rejected", "reason": risk["reason"]}

    # Execute
    if order_type == "market":
        exec_price = _apply_costs(current_price, side, fee_bps, slip_bps, spread_bps)
        return await _fill_order(user_id, ticker, side, qty, exec_price, asset_type, "market", current_price,
                                 strategy=strategy, timeframe=timeframe, regime=regime)
    elif order_type == "limit":
        if limit_price is None or limit_price <= 0:
            return {"status": "rejected", "reason": "limit_price required for limit order"}
        order = {
            "user_id": user_id,
            "ticker": ticker.upper(),
            "asset_type": asset_type,
            "side": side,
            "qty": qty,
            "order_type": "limit",
            "limit_price": float(limit_price),
            "status": "open",
            "strategy": strategy,
            "timeframe": timeframe,
            "regime": regime,
            "placed_at": datetime.utcnow().isoformat(),
        }
        r = await col_orders.insert_one(order)
        order["order_id"] = str(r.inserted_id)
        order.pop("_id", None)
        return {"status": "open", "order": order}
    elif order_type == "stop":
        if stop_price is None or stop_price <= 0:
            return {"status": "rejected", "reason": "stop_price required for stop order"}
        order = {
            "user_id": user_id,
            "ticker": ticker.upper(),
            "asset_type": asset_type,
            "side": side,
            "qty": qty,
            "order_type": "stop",
            "stop_price": float(stop_price),
            "status": "open",
            "strategy": strategy,
            "timeframe": timeframe,
            "regime": regime,
            "placed_at": datetime.utcnow().isoformat(),
        }
        r = await col_orders.insert_one(order)
        order["order_id"] = str(r.inserted_id)
        order.pop("_id", None)
        return {"status": "open", "order": order}
    else:
        return {"status": "rejected", "reason": f"Unsupported order type: {order_type}"}


async def match_resting_orders(price_map: dict = None) -> dict:
    """Walk every open limit/stop order and fill ones whose trigger condition is met.

    price_map is an optional {ticker: price} override; otherwise prices come from the
    data_freshness cache. Runs idempotently — should be invoked from the broadcast
    loop or a scheduler tick.
    """
    price_map = price_map or {}
    open_orders = await col_orders.find({"status": "open"}).to_list(1000)
    filled = 0
    for o in open_orders:
        ticker = o.get("ticker", "")
        price = price_map.get(ticker)
        if price is None:
            cached = data_freshness.get_price(ticker)
            if cached and not cached.get("expired"):
                price = cached["price"]
        if not price or price <= 0:
            continue

        otype = o.get("order_type")
        side = o.get("side", "buy")
        triggered = False
        if otype == "limit":
            lp = float(o.get("limit_price", 0) or 0)
            if lp <= 0:
                continue
            triggered = (side == "buy" and price <= lp) or (side == "sell" and price >= lp)
        elif otype == "stop":
            sp = float(o.get("stop_price", 0) or 0)
            if sp <= 0:
                continue
            # buy-stop triggers when price rises through the stop; sell-stop when it falls
            triggered = (side == "buy" and price >= sp) or (side == "sell" and price <= sp)
        if not triggered:
            continue

        exec_price = _apply_costs(price, side, DEFAULT_FEE_BPS, DEFAULT_SLIPPAGE_BPS, DEFAULT_SPREAD_BPS)
        fill = await _fill_order(
            o["user_id"], ticker, side, float(o["qty"]), exec_price,
            o.get("asset_type", "stock"), otype, price,
            strategy=o.get("strategy"), timeframe=o.get("timeframe"), regime=o.get("regime"),
        )
        if fill.get("status") == "filled":
            await col_orders.update_one(
                {"_id": o["_id"]},
                {"$set": {"status": "filled", "fill_price": exec_price, "filled_at": datetime.utcnow().isoformat()}},
            )
            filled += 1
    return {"checked": len(open_orders), "filled": filled}


async def _fill_order(user_id, ticker, side, qty, exec_price, asset_type, order_type, mark_price,
                      strategy: str = None, timeframe: str = None, regime: str = None):
    """Fill an order: update position book, cash, record order.

    Supports both long and short positions. A position has a signed qty:
      qty > 0 → long
      qty < 0 → short
    A buy reduces a short or adds to a long; a sell reduces a long or opens/adds a short.
    """
    ticker = ticker.upper()
    acct = await get_account(user_id)
    cash = float(acct.get("cash", 0))

    pos = await col_positions.find_one({"user_id": user_id, "ticker": ticker})
    cur_qty = float(pos["qty"]) if pos else 0.0
    cur_avg = float(pos["avg_entry"]) if pos else 0.0

    fill_ts = datetime.utcnow().isoformat()
    realized_pnl = 0.0
    cost_basis_closed = 0.0
    new_qty = cur_qty
    new_avg = cur_avg
    closed_entry_side = None

    if side == "buy":
        # Buy: covers any short first, then adds to long.
        proceeds_or_cost = qty * exec_price  # outflow
        if cur_qty < 0:
            # Cover (some or all) shorts
            cover = min(qty, -cur_qty)
            cost_basis_closed = cover * cur_avg
            realized_pnl = (cur_avg - exec_price) * cover  # short profits if exec < avg
            new_qty = cur_qty + cover
            remaining_buy = qty - cover
            closed_entry_side = "SELL"
            if remaining_buy > 1e-12:
                # Now going long with the remainder
                new_qty += remaining_buy
                new_avg = exec_price
        else:
            # Pure long entry / add
            if proceeds_or_cost > cash:
                return {"status": "rejected", "reason": f"Insufficient cash (${cash:.2f} < ${proceeds_or_cost:.2f})"}
            total_qty = cur_qty + qty
            new_avg = ((cur_qty * cur_avg) + (qty * exec_price)) / total_qty if total_qty > 0 else exec_price
            new_qty = total_qty
        new_cash = cash - proceeds_or_cost
    else:  # sell
        # Sell: closes (some or all) longs first, then opens/adds short.
        if cur_qty > 0:
            close = min(qty, cur_qty)
            cost_basis_closed = close * cur_avg
            realized_pnl = (exec_price - cur_avg) * close
            new_qty = cur_qty - close
            remaining_sell = qty - close
            closed_entry_side = "BUY"
            if remaining_sell > 1e-12:
                new_qty -= remaining_sell  # open short
                new_avg = exec_price
        else:
            # Opening or adding to a short
            total_qty = cur_qty - qty  # more negative
            # Weighted-average entry on negative qty
            new_avg = ((abs(cur_qty) * cur_avg) + (qty * exec_price)) / abs(total_qty) if total_qty != 0 else exec_price
            new_qty = total_qty
        proceeds = qty * exec_price
        new_cash = cash + proceeds

    # Persist position book
    if abs(new_qty) < 1e-9:
        await col_positions.delete_one({"user_id": user_id, "ticker": ticker})
    elif pos:
        await col_positions.update_one(
            {"user_id": user_id, "ticker": ticker},
            {"$set": {"qty": new_qty, "avg_entry": new_avg}},
        )
    else:
        await col_positions.insert_one({
            "user_id": user_id,
            "ticker": ticker,
            "asset_type": asset_type,
            "qty": new_qty,
            "avg_entry": new_avg,
            "opened_at": fill_ts,
        })

    if closed_entry_side and cost_basis_closed > 0:
        await col_trades.insert_one({
            "user_id": user_id,
            "ticker": ticker,
            "asset_type": asset_type,
            "side": closed_entry_side,
            "qty": abs(qty) if abs(new_qty) < 1e-9 else cost_basis_closed / cur_avg,
            "entry_price": cur_avg,
            "exit_price": exec_price,
            "pnl": realized_pnl,
            "pnl_pct": realized_pnl / cost_basis_closed * 100 if cost_basis_closed else 0,
            "broker": "paper",
            "strategy": strategy,
            "timeframe": timeframe,
            "regime": regime,
            "opened_at": pos.get("opened_at") if pos else fill_ts,
            "closed_at": fill_ts,
            "status": "closed",
        })

    await col_accounts.update_one({"user_id": user_id}, {"$set": {"cash": new_cash}})

    order_doc = {
        "user_id": user_id,
        "ticker": ticker,
        "asset_type": asset_type,
        "side": side,
        "qty": qty,
        "order_type": order_type,
        "fill_price": exec_price,
        "mark_price": mark_price,
        "slippage_bps": round((exec_price - mark_price) / mark_price * 10000, 2) if mark_price else 0,
        "realized_pnl": realized_pnl,
        "status": "filled",
        "placed_at": fill_ts,
        "filled_at": fill_ts,
    }
    r = await col_orders.insert_one(order_doc)
    order_doc["order_id"] = str(r.inserted_id)
    order_doc.pop("_id", None)
    log.info(f"filled {side} {qty} {ticker} @ ${exec_price:.4f} for {user_id} (pnl ${realized_pnl:.2f})")
    return {"status": "filled", "order": order_doc}


async def get_orders(user_id: str, status: str = None, limit: int = 50):
    q = {"user_id": user_id}
    if status:
        q["status"] = status
    docs = await col_orders.find(q).sort("placed_at", -1).limit(limit).to_list(limit)
    for d in docs:
        d["_id"] = str(d["_id"])
    return docs


async def get_positions(user_id: str, live_prices: dict = None):
    """Get open positions with unrealized PnL computed against live_prices."""
    live_prices = live_prices or {}
    docs = await col_positions.find({"user_id": user_id}).to_list(100)
    out = []
    total_unrealized = 0.0
    total_value = 0.0
    for d in docs:
        d["_id"] = str(d["_id"])
        ticker = d["ticker"]
        cached = data_freshness.get_price(ticker)
        cached_price = cached["price"] if (cached and cached.get("price")) else None
        current = cached_price if cached_price else live_prices.get(ticker) or d["avg_entry"]
        qty = float(d.get("qty", 0) or 0)
        avg = float(d.get("avg_entry", 0) or 0)
        d["current_price"] = current
        d["side"] = "long" if qty > 0 else ("short" if qty < 0 else "flat")
        d["market_value"] = qty * current
        d["cost_basis"] = qty * avg
        # PnL: long profits when current > avg; short profits when current < avg
        d["unrealized_pnl"] = (current - avg) * qty
        ref_basis = abs(qty * avg)
        d["unrealized_pnl_pct"] = (d["unrealized_pnl"] / ref_basis * 100) if ref_basis else 0
        d["price_age_sec"] = cached["age_sec"] if cached else None
        total_unrealized += d["unrealized_pnl"]
        total_value += d["market_value"]
        out.append(d)
    return {
        "positions": out,
        "total_market_value": round(total_value, 2),
        "total_unrealized_pnl": round(total_unrealized, 2),
    }


async def cancel_order(user_id: str, order_id: str):
    from bson import ObjectId
    try:
        oid = ObjectId(order_id)
    except Exception:
        return {"status": "error", "reason": "Invalid order_id"}
    res = await col_orders.update_one(
        {"_id": oid, "user_id": user_id, "status": "open"},
        {"$set": {"status": "cancelled", "cancelled_at": datetime.utcnow().isoformat()}},
    )
    if res.modified_count == 0:
        return {"status": "error", "reason": "Order not found or not cancellable"}
    return {"status": "cancelled", "order_id": order_id}


async def get_summary(user_id: str, live_prices: dict = None):
    """Account summary: cash, equity, realized, unrealized, total return."""
    acct = await get_account(user_id)
    pos = await get_positions(user_id, live_prices)

    pipeline = [
        {"$match": {"user_id": user_id, "status": "closed", "broker": "paper"}},
        {"$group": {"_id": None, "pnl": {"$sum": "$pnl"}, "count": {"$sum": 1}}},
    ]
    realized = 0.0
    count = 0
    async for r in col_trades.aggregate(pipeline):
        realized = float(r.get("pnl", 0) or 0)
        count = int(r.get("count", 0))

    equity = acct["cash"] + pos["total_market_value"]
    starting = acct["starting_capital"]
    return {
        "starting_capital": starting,
        "cash": round(acct["cash"], 2),
        "market_value": pos["total_market_value"],
        "equity": round(equity, 2),
        "realized_pnl": round(realized, 2),
        "unrealized_pnl": pos["total_unrealized_pnl"],
        "total_pnl": round(realized + pos["total_unrealized_pnl"], 2),
        "total_return_pct": round((equity / starting - 1) * 100, 2) if starting > 0 else 0,
        "closed_trades": count,
        "open_positions": len(pos["positions"]),
    }
