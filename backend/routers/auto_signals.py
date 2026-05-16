from fastapi import APIRouter, Depends
from middleware.auth import get_current_user
from services.auto_signal_scanner import latest_auto_signals, scan_all_auto_signals, scan_auto_signals

router = APIRouter()


@router.get("/latest")
async def latest(broker: str = None, asset_type: str = None, limit: int = 50, user=Depends(get_current_user)):
    return {"signals": await latest_auto_signals(broker_id=broker, asset_type=asset_type, limit=limit)}


@router.post("/scan")
async def scan_now(user=Depends(get_current_user)):
    return await scan_all_auto_signals()


@router.post("/scan/{broker}/{asset_type}")
async def scan_one(broker: str, asset_type: str, timeframe: str = "swing", interval: str = "1d", use_ai: bool = True, user=Depends(get_current_user)):
    return await scan_auto_signals(broker_id=broker, asset_type=asset_type, timeframe=timeframe, interval=interval, use_ai=use_ai)
