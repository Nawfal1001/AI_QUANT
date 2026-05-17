import asyncio
from fastapi import APIRouter, Depends
from middleware.auth import get_current_user
from services.ai_service import get_ai_research, get_ai_signal
from services.gemini_utils import ping as gemini_ping

router = APIRouter()


@router.get("/status")
async def status(user=Depends(get_current_user)):
    """Health check for Gemini. Pings the API with a tiny prompt so the UI can
    show a green/red dot and the operator can tell whether their key is good
    without scraping logs. The ping is done in a thread because the SDK is sync.
    """
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, gemini_ping)


@router.post("/research")
async def research(d: dict, user=Depends(get_current_user)):
    return await get_ai_research(d.get("query", ""), d.get("ticker"), d.get("asset_type", "stock"))


@router.get("/signal/{ticker}")
async def signal(ticker: str, asset_type: str = "stock", user=Depends(get_current_user)):
    return await get_ai_signal(ticker, asset_type)
