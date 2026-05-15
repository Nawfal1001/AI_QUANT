"""
Economic Event Engine.

High-impact macro reports are not normal headline sentiment. This service is
for scheduled releases such as CPI, PPI, PCE, NFP, GDP, retail sales, central
bank statements, inventories, and PMI.

Flow:
1. Maintain/watch an economic calendar.
2. Around release time, ingest actual report text or actual/forecast/previous.
3. Ask macro_analyzer for cross-asset impact.
4. Convert the result into emergency trade requests/signals for forex, gold,
   equities, oil, and crypto bots.

This service does not place orders directly. It writes emergency macro signals
that bot_runner or a dedicated emergency bot can consume.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from database import db
from services.logger import child
from services.macro_analyzer import analyze_macro_report, macro_bias_for_symbol

log = child("economic_event_engine")

col_events = db["economic_events"]
col_macro_signals = db["macro_emergency_signals"]

DEFAULT_EVENT_ASSETS = {
    "USD": [
        {"ticker": "EUR_USD", "asset_type": "forex", "inverse_usd": True},
        {"ticker": "GBP_USD", "asset_type": "forex", "inverse_usd": True},
        {"ticker": "USD_JPY", "asset_type": "forex", "inverse_usd": False},
        {"ticker": "USD_CHF", "asset_type": "forex", "inverse_usd": False},
        {"ticker": "XAUUSD", "asset_type": "gold", "inverse_usd": True},
        {"ticker": "BTC", "asset_type": "crypto", "inverse_usd": True},
        {"ticker": "ETH", "asset_type": "crypto", "inverse_usd": True},
        {"ticker": "SPY", "asset_type": "stock", "inverse_usd": True},
        {"ticker": "QQQ", "asset_type": "stock", "inverse_usd": True},
    ],
    "EUR": [
        {"ticker": "EUR_USD", "asset_type": "forex", "inverse_usd": False},
        {"ticker": "EUR_GBP", "asset_type": "forex", "inverse_usd": False},
        {"ticker": "EUR_JPY", "asset_type": "forex", "inverse_usd": False},
    ],
    "GBP": [
        {"ticker": "GBP_USD", "asset_type": "forex", "inverse_usd": False},
        {"ticker": "EUR_GBP", "asset_type": "forex", "inverse_usd": True},
        {"ticker": "GBP_JPY", "asset_type": "forex", "inverse_usd": False},
    ],
    "JPY": [
        {"ticker": "USD_JPY", "asset_type": "forex", "inverse_usd": True},
        {"ticker": "EUR_JPY", "asset_type": "forex", "inverse_usd": True},
        {"ticker": "GBP_JPY", "asset_type": "forex", "inverse_usd": True},
    ],
    "OIL": [
        {"ticker": "CL", "asset_type": "oil", "inverse_usd": False},
        {"ticker": "USO", "asset_type": "oil", "inverse_usd": False},
    ],
}

HIGH_IMPACT_EVENT_TYPES = {
    "FOMC", "FED_STATEMENT", "FED_MINUTES", "FED_SPEECH", "CPI", "PPI", "PCE", "NFP",
    "GDP", "RETAIL_SALES", "ISM", "PMI", "ECB", "BOE", "BOJ", "OIL", "GEOPOLITICAL",
}


def _now() -> datetime:
    return datetime.utcnow()


def _now_iso() -> str:
    return _now().isoformat()


def _direction_to_signal(direction: str, invert: bool = False) -> str:
    d = (direction or "neutral").lower()
    if invert:
        if d == "bullish":
            d = "bearish"
        elif d == "bearish":
            d = "bullish"
    if d == "bullish":
        return "BUY"
    if d == "bearish":
        return "SELL"
    return "HOLD"


def _asset_group_from_event(event: Dict[str, Any]) -> str:
    ccy = (event.get("currency") or event.get("country") or "USD").upper()
    etype = (event.get("event_type") or "").upper()
    if etype == "OIL":
        return "OIL"
    if ccy in {"US", "USA", "UNITED_STATES"}:
        return "USD"
    if ccy in {"EU", "EUR", "EUROZONE"}:
        return "EUR"
    if ccy in {"UK", "GBP"}:
        return "GBP"
    if ccy in {"JP", "JPY", "JAPAN"}:
        return "JPY"
    return ccy if ccy in DEFAULT_EVENT_ASSETS else "USD"


async def upsert_economic_event(event: Dict[str, Any]) -> Dict[str, Any]:
    """Create/update a scheduled macro event.

    Expected fields: event_id, event_name, event_type, currency, release_time,
    impact, forecast, previous, source_url.
    """
    event_id = event.get("event_id") or f"{event.get('event_type','EVENT')}_{event.get('currency','USD')}_{event.get('release_time','')}_{event.get('event_name','') }"
    doc = {**event, "event_id": event_id, "updated_at": _now_iso()}
    await col_events.replace_one({"event_id": event_id}, doc, upsert=True)
    return doc


async def due_events(window_before_min: int = 5, window_after_min: int = 20) -> List[Dict[str, Any]]:
    now = _now()
    start = now - timedelta(minutes=window_after_min)
    end = now + timedelta(minutes=window_before_min)
    docs = await col_events.find({
        "release_time": {"$gte": start.isoformat(), "$lte": end.isoformat()},
        "impact": {"$in": ["high", "High", "HIGH", "medium", "Medium"]},
        "status": {"$ne": "processed"},
    }).to_list(100)
    return docs


def build_report_text_from_event(event: Dict[str, Any]) -> str:
    parts = [
        f"Event: {event.get('event_name') or event.get('event_type')}",
        f"Currency/Country: {event.get('currency') or event.get('country')}",
        f"Release time UTC: {event.get('release_time')}",
        f"Impact: {event.get('impact')}",
    ]
    for key in ["actual", "forecast", "consensus", "previous", "revision", "statement", "summary", "report_text"]:
        if event.get(key) not in [None, ""]:
            parts.append(f"{key}: {event.get(key)}")
    return "\n".join(parts)


async def process_economic_event(event: Dict[str, Any], use_ai: bool = True, min_confidence: float = 60) -> Dict[str, Any]:
    """Analyze one released report and emit emergency macro signals."""
    report_text = event.get("report_text") or build_report_text_from_event(event)
    event_name = event.get("event_name") or event.get("event_type") or "Economic event"
    macro = await analyze_macro_report(event_name, report_text, market_reaction=event.get("market_reaction"), use_ai=use_ai)
    asset_group = _asset_group_from_event(event)
    candidates = event.get("trade_assets") or DEFAULT_EVENT_ASSETS.get(asset_group, DEFAULT_EVENT_ASSETS["USD"])

    signals = []
    for item in candidates:
        ticker = item["ticker"]
        asset_type = item.get("asset_type", "forex")
        bias = macro_bias_for_symbol(macro, ticker, asset_type)
        signal = _direction_to_signal(bias.get("direction"), invert=bool(item.get("inverse_usd")) and asset_group == "USD")
        confidence = float(bias.get("confidence", 0) or 0)
        if signal == "HOLD" or confidence < min_confidence:
            continue
        doc = {
            "event_id": event.get("event_id"),
            "event_name": event_name,
            "event_type": macro.get("event_type") or event.get("event_type"),
            "currency": event.get("currency"),
            "ticker": ticker,
            "asset_type": asset_type,
            "signal": signal,
            "confidence": confidence,
            "reason": bias.get("reason"),
            "macro_context": {
                "surprise": macro.get("surprise"),
                "risk_mode": macro.get("risk_mode"),
                "time_horizon": macro.get("time_horizon"),
                "trade_instruction": macro.get("trade_instruction"),
                "needs_price_confirmation": macro.get("needs_price_confirmation", True),
                "source": macro.get("source"),
            },
            "status": "pending_confirmation" if macro.get("needs_price_confirmation", True) else "ready",
            "created_at": _now_iso(),
            "expires_at": (_now() + timedelta(minutes=int(event.get("signal_ttl_min", 45)))).isoformat(),
        }
        await col_macro_signals.insert_one(doc)
        signals.append({k: v for k, v in doc.items() if k != "_id"})

    await col_events.update_one({"event_id": event.get("event_id")}, {"$set": {"status": "processed", "processed_at": _now_iso(), "macro_result": macro, "emitted_signals": len(signals)}})
    return {"event_id": event.get("event_id"), "macro": macro, "signals": signals}


async def process_due_events(use_ai: bool = True) -> Dict[str, Any]:
    events = await due_events()
    results = []
    for ev in events:
        try:
            results.append(await process_economic_event(ev, use_ai=use_ai))
        except Exception as e:
            log.exception(f"failed to process economic event {ev.get('event_id')}: {e}")
    return {"processed": len(results), "results": results}


async def list_active_macro_signals(asset_type: Optional[str] = None, limit: int = 50) -> List[Dict[str, Any]]:
    now = _now().isoformat()
    q: Dict[str, Any] = {"expires_at": {"$gte": now}, "status": {"$in": ["ready", "pending_confirmation"]}}
    if asset_type:
        q["asset_type"] = asset_type
    docs = await col_macro_signals.find(q).sort("created_at", -1).limit(limit).to_list(limit)
    for d in docs:
        d["_id"] = str(d["_id"])
    return docs


async def start_economic_event_scheduler(interval_sec: int = 30):
    async def loop():
        while True:
            try:
                await process_due_events(use_ai=True)
            except Exception as e:
                log.exception(f"economic event scheduler error: {e}")
            await asyncio.sleep(interval_sec)
    asyncio.create_task(loop())
    log.info("Economic event scheduler started")
