from fastapi import APIRouter

from services.news_sentiment_provider import get_news_sentiment

router = APIRouter()


@router.get("/{ticker}")
async def sentiment(ticker: str, asset_type: str = "stock"):
    return await get_news_sentiment(ticker, asset_type)
