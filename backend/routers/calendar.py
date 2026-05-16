from fastapi import APIRouter, Depends, HTTPException

from middleware.auth import get_current_user, require_admin
from services.economic_calendar_provider import fetch_calendar, sync_calendar, list_calendar_events

router = APIRouter()


@router.get("/events")
async def events(start_date: str = None, end_date: str = None, limit: int = 200, user=Depends(get_current_user)):
    return {"events": await list_calendar_events(start_date=start_date, end_date=end_date, limit=limit)}


@router.post("/sync")
async def sync(start_date: str = None, end_date: str = None, user=Depends(require_admin)):
    try:
        return await sync_calendar(start_date=start_date, end_date=end_date)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/preview")
async def preview(start_date: str = None, end_date: str = None, user=Depends(require_admin)):
    try:
        return {"events": await fetch_calendar(start_date=start_date, end_date=end_date)}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
