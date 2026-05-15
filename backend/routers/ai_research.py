from fastapi import APIRouter, Depends
from middleware.auth import get_current_user
from services.ai_service import get_ai_research, get_ai_signal

router = APIRouter()


@router.post("/research")
async def research(d: dict, user=Depends(get_current_user)):
    return await get_ai_research(d.get("query", ""), d.get("ticker"), d.get("asset_type", "stock"))


@router.get("/signal/{ticker}")
async def signal(ticker: str, asset_type: str = "stock", user=Depends(get_current_user)):
    return await get_ai_signal(ticker, asset_type)
