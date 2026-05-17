from fastapi import APIRouter, Depends, HTTPException, Query
from typing import Optional

from middleware.auth import get_current_user, require_admin
from services.economic_calendar_provider import fetch_calendar, sync_calendar, list_calendar_events
from services.calendar_ai import get_briefing, enrich_events
from services.calendar_impact_service import analyze_event_impact, refresh_and_analyze_due

router = APIRouter()

@router.get('/events')
async def events(start_date: Optional[str] = None, end_date: Optional[str] = None, limit: int = Query(200, ge=1, le=500), with_ai: bool = Query(False), user=Depends(get_current_user)):
    docs = await list_calendar_events(start_date=start_date, end_date=end_date, limit=limit)
    if with_ai:
        docs = await enrich_events(docs)
    return {'events': docs}

@router.get('/events/{event_id}/briefing')
async def event_briefing(event_id: str, user=Depends(get_current_user)):
    from database import db
    ev = await db['economic_events'].find_one({'event_id': event_id})
    if not ev:
        raise HTTPException(404, f'Event {event_id} not found')
    ev['_id'] = str(ev['_id'])
    return await get_briefing(ev)

@router.get('/events/{event_id}/impact')
async def event_impact(event_id: str, force: bool = False, user=Depends(get_current_user)):
    result = await analyze_event_impact(event_id, use_ai=True, force=force)
    if not result.get('ok'):
        raise HTTPException(status_code=400, detail=result.get('error'))
    return result

@router.post('/sync')
async def sync(start_date: Optional[str] = None, end_date: Optional[str] = None, analyze_due: bool = True, user=Depends(require_admin)):
    try:
        if analyze_due:
            return await refresh_and_analyze_due(start_date=start_date, end_date=end_date, use_ai=True)
        return await sync_calendar(start_date=start_date, end_date=end_date)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.get('/preview')
async def preview(start_date: Optional[str] = None, end_date: Optional[str] = None, user=Depends(require_admin)):
    try:
        return {'events': await fetch_calendar(start_date=start_date, end_date=end_date)}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
