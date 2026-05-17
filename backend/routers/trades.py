from datetime import datetime, timedelta
from typing import Any, Dict, Optional

from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException

from database import db
from middleware.auth import get_current_user, scope_filter

router = APIRouter()

SOURCE_COLLECTIONS = {
    "open": "open_trades",
    "open_trades": "open_trades",
    "autotrader_open": "open_trades",
    "history": "trade_history",
    "trade_history": "trade_history",
    "autotrader_history": "trade_history",
    "paper": "paper_positions",
    "paper_position": "paper_positions",
    "paper_positions": "paper_positions",
    "paper_order": "paper_orders",
    "paper_orders": "paper_orders",
    "paper_trade": "trades",
    "paper_history": "trades",
    "paper_trades": "trades",
    "closed": "trades",
    "trades": "trades",
    "bot": "bot_trades",
    "bot_trades": "bot_trades",
    "broker": "broker_trades",
    "broker_trades": "broker_trades",
    "emergency": "macro_emergency_trades",
    "macro": "macro_emergency_trades",
}

def _to_json(doc: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(doc or {})
    if out.get("_id") is not None:
        out["_id"] = str(out["_id"])
    return out

def _parse_dt(value: Any) -> Optional[datetime]:
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).replace(tzinfo=None)
    except Exception:
        return None

def _num(*vals):
    for v in vals:
        try:
            if v is not None and v != "": return float(v)
        except Exception: pass
    return None

def _field(doc: Dict[str, Any], *names, default=None):
    for n in names:
        if doc.get(n) not in (None, ""):
            return doc.get(n)
    return default

def _normalize_trade(coll: str, doc: Dict[str, Any]) -> Dict[str, Any]:
    t = dict(doc)
    if coll == "paper_positions":
        qty = _num(t.get("qty")) or 0
        t.setdefault("status", "open")
        t.setdefault("entry_price", t.get("avg_entry"))
        t.setdefault("signal", "BUY" if qty >= 0 else "SELL")
        t.setdefault("side", "long" if qty >= 0 else "short")
        t.setdefault("source", "paper_position")
    elif coll == "paper_orders":
        t.setdefault("entry_price", t.get("fill_price") or t.get("limit_price") or t.get("stop_price") or t.get("mark_price"))
        t.setdefault("signal", str(t.get("side", "")).upper())
        t.setdefault("opened_at", t.get("filled_at") or t.get("placed_at"))
        t.setdefault("source", "paper_order")
    elif coll == "trades":
        t.setdefault("source", t.get("broker") or "closed_trade")
        if t.get("exit_price") and not t.get("close_price"):
            t["close_price"] = t.get("exit_price")
    return t

async def _find_trade(source: str, trade_id: str, user: Dict[str, Any]):
    coll_name = SOURCE_COLLECTIONS.get(source)
    if not coll_name:
        raise HTTPException(400, f"unsupported trade source: {source}")
    q = scope_filter(user)
    candidates = []
    try: candidates.append({**q, "_id": ObjectId(trade_id)})
    except Exception: pass
    for key in ["trade_id", "id", "order_id", "client_order_id", "signal_id"]:
        candidates.append({**q, key: trade_id})
    if coll_name == "trades" and source.startswith("paper"):
        candidates = [{**c, "broker": "paper"} for c in candidates]
    for cq in candidates:
        doc = await db[coll_name].find_one(cq)
        if doc:
            return coll_name, _normalize_trade(coll_name, _to_json(doc))
    raise HTTPException(404, "trade not found")

def _interval_for_trade(trade: Dict[str, Any]) -> str:
    tf = str(_field(trade, "timeframe", "interval", default="15m") or "15m")
    aliases = {"scalping": "5m", "intraday": "30m", "swing": "1d", "position": "1wk", "1w": "1wk"}
    return aliases.get(tf, tf)

def _asset_type(trade: Dict[str, Any]) -> str:
    return str(_field(trade, "asset_type", "type", default="stock") or "stock").lower()

def _ticker(trade: Dict[str, Any]) -> str:
    return str(_field(trade, "ticker", "symbol", "asset", default="") or "").upper()

async def _fetch_candles(trade: Dict[str, Any], source: str):
    ticker = _ticker(trade)
    if not ticker: return []
    atype = _asset_type(trade); interval = _interval_for_trade(trade)
    opened = _parse_dt(_field(trade, "opened_at", "entry_time", "created_at", "timestamp", "placed_at")) or datetime.utcnow() - timedelta(days=5)
    closed = _parse_dt(_field(trade, "closed_at", "exit_time", "updated_at", "filled_at")) or datetime.utcnow()
    start = opened - timedelta(days=3); end = closed + timedelta(days=2)
    try:
        from services.backtest_engine import fetch_history
        df = await fetch_history(ticker, atype, start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d"), interval)
        if df is None or len(df) == 0: return []
        df = df.rename(columns={c: str(c).lower() for c in df.columns})
        time_col = next((c for c in ["time", "timestamp", "date", "datetime"] if c in df.columns), None)
        rows = []
        for idx, r in df.tail(1000).iterrows():
            raw_time = r.get(time_col) if time_col else idx
            dt = _parse_dt(raw_time) or (raw_time.to_pydatetime().replace(tzinfo=None) if hasattr(raw_time, "to_pydatetime") else None)
            if not dt: continue
            rows.append({"time": int(dt.timestamp()), "open": float(r.get("open")), "high": float(r.get("high")), "low": float(r.get("low")), "close": float(r.get("close")), "volume": float(r.get("volume", 0) or 0)})
        return rows
    except Exception:
        return []

def _marker_time(dt: Optional[datetime], candles):
    if dt: return int(dt.timestamp())
    if candles: return candles[-1]["time"]
    return int(datetime.utcnow().timestamp())

def _chart_payload(source: str, coll: str, trade: Dict[str, Any], candles):
    entry = _num(_field(trade, "entry_price", "entry", "avg_entry", "open_price", "price", "fill_price"))
    exitp = _num(_field(trade, "close_price", "exit_price", "closed_price"))
    sl = _num(_field(trade, "sl", "stop_loss", "stop")); tp = _num(_field(trade, "tp", "take_profit", "target"))
    opened = _parse_dt(_field(trade, "opened_at", "entry_time", "created_at", "timestamp", "placed_at"))
    closed = _parse_dt(_field(trade, "closed_at", "exit_time", "filled_at")) if exitp is not None else None
    signal = str(_field(trade, "signal", "side", default="") or "").upper(); is_sell = "SELL" in signal or signal == "SHORT"
    markers=[]
    if entry is not None: markers.append({"time": _marker_time(opened, candles), "position": "aboveBar" if is_sell else "belowBar", "color": "#58a6ff", "shape": "arrowDown" if is_sell else "arrowUp", "text": f"ENTRY {entry:.4f}"})
    if exitp is not None: markers.append({"time": _marker_time(closed, candles), "position": "belowBar" if is_sell else "aboveBar", "color": "#e3b341", "shape": "circle", "text": f"EXIT {exitp:.4f}"})
    lines=[]
    for key, price, color, title in [("entry", entry, "#58a6ff", "Entry"), ("tp", tp, "#3fb950", "TP"), ("sl", sl, "#f85149", "SL"), ("exit", exitp, "#e3b341", "Exit")]:
        if price is not None: lines.append({"key": key, "price": price, "color": color, "title": title})
    return {"source": source, "collection": coll, "status": trade.get("status"), "trade": trade, "candles": candles, "markers": markers, "price_lines": lines}

@router.get("/inspect/{source}/{trade_id}")
async def inspect_trade(source: str, trade_id: str, user=Depends(get_current_user)):
    coll, trade = await _find_trade(source, trade_id, user)
    candles = await _fetch_candles(trade, source)
    return _chart_payload(source, coll, trade, candles)
