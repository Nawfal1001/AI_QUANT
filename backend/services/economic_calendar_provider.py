"""
Economic calendar provider integration.

Primary free provider: Finnhub economic calendar.
Keys are read from environment variables:
- ECONOMIC_CALENDAR_PROVIDER=finnhub
- FINNHUB_API_KEY=<your key>

This service normalizes provider events into the economic_events schema used by
economic_event_engine.py.
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

import httpx

from database import db
from services.economic_event_engine import upsert_economic_event
from services.logger import child

log = child("economic_calendar_provider")

HIGH_KEYWORDS = {
    "cpi": "CPI",
    "consumer price": "CPI",
    "ppi": "PPI",
    "producer price": "PPI",
    "pce": "PCE",
    "payroll": "NFP",
    "nonfarm": "NFP",
    "unemployment": "NFP",
    "gdp": "GDP",
    "retail sales": "RETAIL_SALES",
    "fomc": "FOMC",
    "fed": "FED_STATEMENT",
    "interest rate": "RATE_DECISION",
    "rate decision": "RATE_DECISION",
    "pmi": "PMI",
    "ism": "ISM",
    "ecb": "ECB",
    "boe": "BOE",
    "boj": "BOJ",
    "crude oil": "OIL",
    "inventories": "OIL",
}


def _provider() -> str:
    return os.getenv("ECONOMIC_CALENDAR_PROVIDER", "finnhub").lower()


def _event_type(name: str) -> str:
    lower = (name or "").lower()
    for kw, etype in HIGH_KEYWORDS.items():
        if kw in lower:
            return etype
    return "ECONOMIC"


def _impact(name: str, raw_impact: Any = None) -> str:
    if raw_impact:
        s = str(raw_impact).lower()
        if "high" in s or s in {"3", "important"}:
            return "high"
        if "medium" in s or s in {"2"}:
            return "medium"
        if "low" in s or s in {"1"}:
            return "low"
    etype = _event_type(name)
    return "high" if etype in {"CPI", "PPI", "PCE", "NFP", "GDP", "RETAIL_SALES", "FOMC", "FED_STATEMENT", "RATE_DECISION", "ECB", "BOE", "BOJ", "OIL"} else "medium"


def _parse_time(item: Dict[str, Any]) -> Optional[str]:
    raw = item.get("time") or item.get("datetime") or item.get("date")
    if not raw:
        return None
    if isinstance(raw, (int, float)):
        return datetime.utcfromtimestamp(raw).isoformat()
    s = str(raw).replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(s).replace(tzinfo=None).isoformat()
    except Exception:
        return str(raw)[:19]


def _normalize_finnhub(item: Dict[str, Any]) -> Dict[str, Any]:
    name = item.get("event") or item.get("name") or item.get("title") or "Economic event"
    country = item.get("country") or item.get("region") or "US"
    currency = item.get("currency") or ("USD" if str(country).upper() in {"US", "USA", "UNITED STATES"} else str(country).upper())
    release_time = _parse_time(item) or datetime.utcnow().isoformat()
    etype = _event_type(name)
    event_id = f"finnhub_{country}_{etype}_{release_time}_{name}".replace(" ", "_")[:180]
    return {
        "event_id": event_id,
        "event_name": name,
        "event_type": etype,
        "country": country,
        "currency": currency,
        "release_time": release_time,
        "impact": _impact(name, item.get("impact") or item.get("importance")),
        "actual": item.get("actual"),
        "forecast": item.get("forecast") or item.get("estimate"),
        "previous": item.get("prev") or item.get("previous"),
        "source": "finnhub",
        "source_payload": item,
        "status": item.get("status", "scheduled"),
    }


async def fetch_finnhub_calendar(start_date: str, end_date: str) -> List[Dict[str, Any]]:
    key = os.getenv("FINNHUB_API_KEY", "")
    if not key:
        raise RuntimeError("FINNHUB_API_KEY is not configured")
    params = {"from": start_date, "to": end_date, "token": key}
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.get("https://finnhub.io/api/v1/calendar/economic", params=params)
        r.raise_for_status()
        data = r.json()
    items = data.get("economicCalendar") or data.get("calendar") or []
    return [_normalize_finnhub(x) for x in items]


async def fetch_calendar(start_date: Optional[str] = None, end_date: Optional[str] = None) -> List[Dict[str, Any]]:
    start_date = start_date or datetime.utcnow().date().isoformat()
    end_date = end_date or (datetime.utcnow().date() + timedelta(days=14)).isoformat()
    provider = _provider()
    if provider == "finnhub":
        return await fetch_finnhub_calendar(start_date, end_date)
    if provider == "manual":
        return []
    raise RuntimeError(f"Unsupported ECONOMIC_CALENDAR_PROVIDER={provider}")


async def sync_calendar(start_date: Optional[str] = None, end_date: Optional[str] = None) -> Dict[str, Any]:
    events = await fetch_calendar(start_date, end_date)
    synced = []
    for ev in events:
        try:
            doc = await upsert_economic_event(ev)
            synced.append(doc.get("event_id"))
        except Exception as e:
            log.warning(f"failed to upsert calendar event {ev.get('event_name')}: {e}")
    return {"provider": _provider(), "fetched": len(events), "synced": len(synced), "event_ids": synced[:50]}


async def list_calendar_events(start_date: Optional[str] = None, end_date: Optional[str] = None, limit: int = 200) -> List[Dict[str, Any]]:
    q: Dict[str, Any] = {}
    if start_date or end_date:
        q["release_time"] = {}
        if start_date:
            q["release_time"]["$gte"] = start_date
        if end_date:
            q["release_time"]["$lte"] = end_date
    docs = await db["economic_events"].find(q).sort("release_time", 1).limit(limit).to_list(limit)
    for d in docs:
        d["_id"] = str(d["_id"])
    return docs
