from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from typing import Any, Dict, List, Optional

from database import db
from middleware.auth import get_current_user, require_admin
from services.economic_event_engine import (
    upsert_economic_event,
    process_economic_event,
    process_due_events,
    list_active_macro_signals,
)
from services.macro_analyzer import analyze_macro_report, analyze_macro_impact
from services.emergency_macro_runner import is_running as emergency_runner_running
from services.bot_runner import is_running as bot_runner_running

router = APIRouter()


class EconomicEventIn(BaseModel):
    event_id: Optional[str] = None
    event_name: str
    event_type: str
    currency: str = "USD"
    release_time: str
    impact: str = "high"
    actual: Optional[str] = None
    forecast: Optional[str] = None
    previous: Optional[str] = None
    report_text: Optional[str] = None
    source_url: Optional[str] = None
    trade_assets: Optional[List[Dict[str, Any]]] = None


class ReportAnalysisIn(BaseModel):
    event_name: str = "Macro report"
    report_text: str = Field(..., min_length=10)
    market_reaction: Optional[Dict[str, Any]] = None
    use_ai: bool = True


@router.get("/status")
async def status(user=Depends(get_current_user)):
    active_signals = await list_active_macro_signals(limit=20)
    pending_events = await db["economic_events"].count_documents({"status": {"$ne": "processed"}})
    return {
        "bot_runner": bot_runner_running(),
        "emergency_macro_runner": emergency_runner_running(),
        "pending_events": pending_events,
        "active_macro_signals": len(active_signals),
    }


@router.post("/events")
async def create_or_update_event(payload: EconomicEventIn, user=Depends(require_admin)):
    """Macro events drive global trading decisions; admin only."""
    doc = payload.model_dump(exclude_none=True)
    doc["created_by"] = user["id"]
    return await upsert_economic_event(doc)


@router.get("/events")
async def list_events(limit: int = Query(50, ge=1, le=200), user=Depends(get_current_user)):
    docs = await db["economic_events"].find({}).sort("release_time", -1).limit(limit).to_list(limit)
    for d in docs:
        d["_id"] = str(d["_id"])
    return docs


@router.post("/events/process-due")
async def process_due(user=Depends(require_admin)):
    return await process_due_events(use_ai=True)


@router.post("/events/{event_id}/process")
async def process_event(event_id: str, user=Depends(require_admin)):
    ev = await db["economic_events"].find_one({"event_id": event_id})
    if not ev:
        return {"status": "not_found", "event_id": event_id}
    return await process_economic_event(ev, use_ai=True)


@router.get("/signals")
async def signals(asset_type: Optional[str] = None, limit: int = Query(50, ge=1, le=200), user=Depends(get_current_user)):
    return await list_active_macro_signals(asset_type=asset_type, limit=limit)


@router.post("/analyze-report")
async def analyze_report(payload: ReportAnalysisIn, user=Depends(get_current_user)):
    return await analyze_macro_report(payload.event_name, payload.report_text, market_reaction=payload.market_reaction, use_ai=payload.use_ai)


@router.post("/analyze-latest")
async def analyze_latest(user=Depends(get_current_user)):
    return await analyze_macro_impact(use_ai=True)
