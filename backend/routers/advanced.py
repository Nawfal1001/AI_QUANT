from fastapi import APIRouter, Depends
from middleware.auth import get_current_user
from services.volume_profile import get_volume_profile
from services.microstructure import get_microstructure
from services.llm_sentiment import get_llm_sentiment

router = APIRouter()


@router.get("/volume-profile/{ticker}")
async def vp(ticker: str, asset_type: str = "stock", user=Depends(get_current_user)):
    return await get_volume_profile(ticker.upper(), asset_type)


@router.get("/microstructure/{ticker}")
async def micro(ticker: str, asset_type: str = "crypto", user=Depends(get_current_user)):
    return await get_microstructure(ticker.upper(), asset_type)


@router.get("/llm-sentiment/{ticker}")
async def sentiment(ticker: str, asset_type: str = "stock", user=Depends(get_current_user)):
    return await get_llm_sentiment(ticker.upper(), asset_type)
