"""
News Guard.

Pauses normal bots around high-impact economic events unless the bot is marked
as an emergency macro bot.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Dict, Optional

from database import db


async def should_pause_for_news(bot: dict, asset_type: Optional[str] = None) -> Dict:
    if bot.get("bot_role") == "emergency_macro" or bot.get("ignore_news_guard"):
        return {"pause": False, "reason": "emergency/ignored"}
    if not bot.get("pause_on_high_impact_news", True):
        return {"pause": False, "reason": "disabled"}

    now = datetime.utcnow()
    before = int(bot.get("news_pause_before_min", 10) or 10)
    after = int(bot.get("news_pause_after_min", 20) or 20)
    start = (now - timedelta(minutes=after)).isoformat()
    end = (now + timedelta(minutes=before)).isoformat()

    q = {
        "release_time": {"$gte": start, "$lte": end},
        "impact": {"$in": ["high", "High", "HIGH"]},
    }
    ev = await db["economic_events"].find_one(q, sort=[("release_time", 1)])
    if not ev:
        return {"pause": False, "reason": "no high-impact event"}
    return {
        "pause": True,
        "reason": f"paused for high-impact news: {ev.get('event_name') or ev.get('event_type')}",
        "event_id": ev.get("event_id"),
        "event_name": ev.get("event_name"),
        "release_time": ev.get("release_time"),
    }
