from fastapi import APIRouter
from services.market_service import get_stock,get_crypto,get_movers,search
router=APIRouter()
@router.get("/stock/{ticker}")
async def stock(ticker:str,range:str="1mo"): return await get_stock(ticker,range)
@router.get("/crypto/{symbol}")
async def crypto(symbol:str,range:str="1mo"): return await get_crypto(symbol,range)
@router.get("/search")
async def search_assets(q:str=""): return await search(q)
@router.get("/top-movers")
async def movers(asset_type:str="all"): return await get_movers(asset_type)
