from fastapi import APIRouter

from services.market_context import market_context

router = APIRouter()


@router.get("/{symbol}")
async def get_context(symbol: str, asset_type: str = "crypto"):
    return await market_context(symbol, asset_type)
