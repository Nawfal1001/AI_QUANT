"""
AI commentary for economic calendar events.

For each event we produce TWO Gemini-Flash-generated briefings:

1. **pre-event** ("what to watch") — describes the event, expected ranges, and
   the playbook if the print comes in hawkish / dovish / in-line. Cached for a
   long TTL because it doesn't depend on the actual print.

2. **post-event** ("what now") — once `actual` is populated by the calendar
   sync or a manual upsert, summarise the surprise vs forecast and the
   cross-asset reaction. Re-runs whenever `actual` changes.

Both responses are strict JSON so the frontend can render structured cards.
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Dict, Optional

from database import db
from services.gemini_utils import (
    gemini_available, get_model, get_model_name,
    json_only_guardrails, parse_json_object,
)
from services.logger import child

log = child("calendar_ai")

col_events = db["economic_events"]
col_cache = db["calendar_ai_cache"]


def _now_iso() -> str:
    return datetime.utcnow().isoformat()


def _briefing_key(event: Dict[str, Any], kind: str) -> str:
    return f"{event.get('event_id') or event.get('event_name')}::{kind}"


def _has_actual(event: Dict[str, Any]) -> bool:
    return event.get("actual") not in (None, "", "N/A")


def _event_label(event: Dict[str, Any]) -> str:
    name = event.get("event_name") or event.get("event_type") or "Economic event"
    currency = event.get("currency") or event.get("country") or "USD"
    when = event.get("release_time") or ""
    return f"{name} ({currency}) @ {when}"


PRE_BRIEFING_SCHEMA = """{
  "summary": "1-sentence what-the-event-is",
  "expected": "1-2 sentence what the market is pricing in (use forecast vs previous if given)",
  "scenarios": [
    {"surprise": "hawkish_upside|dovish_downside|in_line", "playbook": "1-2 sentence cross-asset reaction"}
  ],
  "primary_assets": ["USD", "GOLD", "EQUITIES", "CRYPTO", "OIL", "RATES"],
  "watch_for": "1-2 sentence what subtle data point to focus on (revisions, components, tone)",
  "confidence": 0
}"""

POST_BRIEFING_SCHEMA = """{
  "headline": "1-sentence what happened",
  "surprise": "hawkish|dovish|inflationary|disinflationary|growth_positive|growth_negative|in_line",
  "cross_asset": {
    "USD": "bullish|bearish|neutral",
    "GOLD": "bullish|bearish|neutral",
    "EQUITIES": "bullish|bearish|neutral",
    "CRYPTO": "bullish|bearish|neutral",
    "OIL": "bullish|bearish|neutral"
  },
  "playbook": "2-3 sentence what to do over the next session",
  "invalidation": "1 sentence what would flip the read",
  "confidence": 0
}"""


def _build_pre_prompt(event: Dict[str, Any]) -> str:
    rules = """
- Do not invent the actual number — only the forecast / previous given.
- Output JSON only. No commentary outside JSON.
- confidence reflects how well-anchored the consensus is, not how dramatic.
- Use "in_line" as a scenario when consensus has narrow dispersion.
- watch_for should mention subtle items: core vs headline, revisions, components.
""".strip()
    prompt = json_only_guardrails(
        "preview an upcoming economic release for traders",
        PRE_BRIEFING_SCHEMA, rules,
    )
    facts = {
        "event_name": event.get("event_name"),
        "event_type": event.get("event_type"),
        "currency": event.get("currency"),
        "country": event.get("country"),
        "release_time_utc": event.get("release_time"),
        "impact": event.get("impact"),
        "forecast": event.get("forecast"),
        "previous": event.get("previous"),
    }
    prompt += f"\n\nEvent JSON: {json.dumps(facts, default=str)[:6000]}"
    return prompt


def _build_post_prompt(event: Dict[str, Any]) -> str:
    rules = """
- Anchor the surprise classification to actual vs forecast (and revisions vs previous).
- Output JSON only.
- cross_asset must be one of bullish | bearish | neutral per key.
- playbook should suggest direction + time horizon (intraday / next session / weekly).
- invalidation should describe a concrete price/data event that would flip the read.
""".strip()
    prompt = json_only_guardrails(
        "interpret a just-released economic print for traders",
        POST_BRIEFING_SCHEMA, rules,
    )
    facts = {
        "event_name": event.get("event_name"),
        "event_type": event.get("event_type"),
        "currency": event.get("currency"),
        "country": event.get("country"),
        "release_time_utc": event.get("release_time"),
        "impact": event.get("impact"),
        "forecast": event.get("forecast"),
        "previous": event.get("previous"),
        "actual": event.get("actual"),
        "market_reaction": event.get("market_reaction"),
    }
    prompt += f"\n\nEvent JSON: {json.dumps(facts, default=str)[:6000]}"
    return prompt


def _empty(kind: str, reason: str) -> Dict[str, Any]:
    return {"kind": kind, "available": False, "reason": reason, "model": get_model_name(), "generated_at": _now_iso()}


async def _generate(event: Dict[str, Any], kind: str) -> Dict[str, Any]:
    if not gemini_available():
        return _empty(kind, "AI unavailable: GEMINI_API_KEY not configured")
    try:
        prompt = _build_pre_prompt(event) if kind == "pre" else _build_post_prompt(event)
        model = get_model()
        resp = model.generate_content(prompt)
        text = resp.text or ""
        data = parse_json_object(text, {})
        if not data:
            return _empty(kind, "Gemini returned no JSON")
        return {"kind": kind, "available": True, "model": get_model_name(), "generated_at": _now_iso(), **data}
    except Exception as e:
        log.warning(f"calendar AI {kind} briefing failed for {_event_label(event)}: {e}")
        return _empty(kind, f"Gemini error: {str(e)[:160]}")


async def get_briefing(event: Dict[str, Any], use_cache: bool = True) -> Dict[str, Any]:
    """Return pre-event AND (if applicable) post-event briefings.

    Caches per (event_id, kind, actual). When the `actual` changes, the
    post-event briefing is regenerated.
    """
    out: Dict[str, Any] = {"event_id": event.get("event_id"), "pre": None, "post": None}

    # Pre-event briefing: cache key depends on forecast/previous (changes
    # rarely so cache is effectively forever once written).
    pre_key = _briefing_key(event, "pre")
    pre_cached = await col_cache.find_one({"_id": pre_key}) if use_cache else None
    if pre_cached and pre_cached.get("forecast") == event.get("forecast") and pre_cached.get("previous") == event.get("previous"):
        pre_cached.pop("_id", None)
        out["pre"] = pre_cached
    else:
        pre = await _generate(event, "pre")
        await col_cache.replace_one(
            {"_id": pre_key},
            {"_id": pre_key, "forecast": event.get("forecast"), "previous": event.get("previous"), **pre},
            upsert=True,
        )
        out["pre"] = pre

    # Post-event briefing: only if `actual` is present. Cache invalidates when
    # `actual` changes (e.g. a revision).
    if _has_actual(event):
        post_key = _briefing_key(event, "post")
        post_cached = await col_cache.find_one({"_id": post_key}) if use_cache else None
        if post_cached and post_cached.get("actual") == event.get("actual"):
            post_cached.pop("_id", None)
            out["post"] = post_cached
        else:
            post = await _generate(event, "post")
            await col_cache.replace_one(
                {"_id": post_key},
                {"_id": post_key, "actual": event.get("actual"), **post},
                upsert=True,
            )
            out["post"] = post
    return out


async def enrich_events(events: list, use_cache: bool = True) -> list:
    """Attach `ai` field to each event (with `pre` and optional `post`)."""
    out = []
    for ev in events:
        try:
            ai = await get_briefing(ev, use_cache=use_cache)
        except Exception as e:
            log.warning(f"enrich_events failed for {_event_label(ev)}: {e}")
            ai = {"event_id": ev.get("event_id"), "pre": _empty("pre", str(e)[:160]), "post": None}
        item = {**ev, "ai": ai}
        item.pop("_id", None)
        out.append(item)
    return out
