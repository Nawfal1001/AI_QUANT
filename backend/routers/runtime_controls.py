"""
Runtime controls — admin-managed toggles for the trading stack.

Exposes the runtime_controls service to the frontend so an operator can
flip live trading, the auto-trader, the bot runner, the macro engine, and
the live-confirmation requirement at runtime without touching the backend.

Live-trading is double-gated:
- server-side `LIVE_TRADING_ENABLED=true` env (hard lock)
  OR `ALLOW_FRONTEND_LIVE_OVERRIDE=true` to let this UI toggle do the job.
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional

from middleware.auth import get_current_user, require_admin
from services.runtime_controls import get_runtime_controls, update_runtime_controls

router = APIRouter()


class ControlsUpdate(BaseModel):
    live_trading_enabled: Optional[bool] = None
    auto_trader_enabled: Optional[bool] = None
    normal_bots_enabled: Optional[bool] = None
    emergency_macro_enabled: Optional[bool] = None
    economic_events_enabled: Optional[bool] = None
    require_live_confirmation: Optional[bool] = None


@router.get("/")
async def read(user=Depends(get_current_user)):
    """Anyone signed in can read the current state (for status badges in the UI)."""
    return await get_runtime_controls()


@router.patch("/")
async def write(payload: ControlsUpdate, user=Depends(require_admin)):
    """Admin-only: flip any of the runtime toggles."""
    updates = {k: v for k, v in payload.model_dump().items() if v is not None}
    if not updates:
        raise HTTPException(400, "No fields to update")
    return await update_runtime_controls(updates, user_id=user.get("id"))
