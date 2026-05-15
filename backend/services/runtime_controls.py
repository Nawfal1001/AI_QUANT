"""
Runtime trading controls.

Central app-level switches that can be managed from the frontend/admin UI.
These do not remove broker/risk checks. They provide a database-backed control
plane for live trading, bot runner, emergency macro runner, and auto-trader.

LIVE_TRADING_ENABLED remains a server hard-lock unless ALLOW_FRONTEND_LIVE_OVERRIDE=true.
"""
from __future__ import annotations

import os
from datetime import datetime
from typing import Any, Dict

from database import db

col = db["runtime_controls"]

DEFAULT_CONTROLS: Dict[str, Any] = {
    "live_trading_enabled": False,
    "auto_trader_enabled": False,
    "normal_bots_enabled": True,
    "emergency_macro_enabled": True,
    "economic_events_enabled": True,
    "require_live_confirmation": True,
    "updated_at": None,
    "updated_by": None,
}


def _hard_live_env_enabled() -> bool:
    return os.getenv("LIVE_TRADING_ENABLED", "").lower() == "true"


def _frontend_override_allowed() -> bool:
    return os.getenv("ALLOW_FRONTEND_LIVE_OVERRIDE", "").lower() == "true"


async def get_runtime_controls() -> Dict[str, Any]:
    doc = await col.find_one({"_id": "global"})
    if not doc:
        doc = {"_id": "global", **DEFAULT_CONTROLS}
        await col.insert_one(doc)
    doc.pop("_id", None)
    merged = {**DEFAULT_CONTROLS, **doc}
    merged["server_live_hard_lock"] = not _hard_live_env_enabled()
    merged["frontend_live_override_allowed"] = _frontend_override_allowed()
    merged["effective_live_trading_enabled"] = bool(merged.get("live_trading_enabled")) and (_hard_live_env_enabled() or _frontend_override_allowed())
    return merged


async def update_runtime_controls(updates: Dict[str, Any], user_id: str | None = None) -> Dict[str, Any]:
    allowed = set(DEFAULT_CONTROLS.keys()) - {"updated_at", "updated_by"}
    clean = {k: v for k, v in updates.items() if k in allowed}
    bool_fields = {
        "live_trading_enabled", "auto_trader_enabled", "normal_bots_enabled",
        "emergency_macro_enabled", "economic_events_enabled", "require_live_confirmation",
    }
    for key in bool_fields:
        if key in clean:
            clean[key] = bool(clean[key])
    clean["updated_at"] = datetime.utcnow().isoformat()
    clean["updated_by"] = user_id
    await col.update_one({"_id": "global"}, {"$set": clean}, upsert=True)
    return await get_runtime_controls()


async def is_live_trading_effectively_enabled() -> bool:
    controls = await get_runtime_controls()
    return bool(controls.get("effective_live_trading_enabled"))


async def is_normal_bots_enabled() -> bool:
    return bool((await get_runtime_controls()).get("normal_bots_enabled", True))


async def is_emergency_macro_enabled() -> bool:
    return bool((await get_runtime_controls()).get("emergency_macro_enabled", True))


async def is_economic_events_enabled() -> bool:
    return bool((await get_runtime_controls()).get("economic_events_enabled", True))


async def is_auto_trader_enabled() -> bool:
    return bool((await get_runtime_controls()).get("auto_trader_enabled", False))
