"""
News and sentiment providers.

Primary optional provider: Alpha Vantage NEWS_SENTIMENT.
Fallback: Yahoo Finance RSS.

API keys are intentionally read from environment variables. Do not hardcode keys
in the repository.
"""
from __future__ import annotations

import os
from typing import Any, Dict, List

import feedparser
import httpx

POS_WORDS = ["surge", "gain", "bull", "beat", "rise", "growth", "profit", "strong", "up", "upgrade", "outperform"]
NEG_WORDS = ["drop", "fall", "bear", "miss", "loss", "weak", "crash", "concern", "down", "downgrade", "underperform"]


def _score_headlines(headlines: List[str]) -> int:
    score = 0
    for h in headlines:
        hl = h.lower()
        score += sum(1 for w in POS_WORDS if w in hl)
        score -= sum(1 for w in NEG_WORDS if w in hl)
    return score


def _overall(score: float) -> str:
    return "bullish" if score > 2 else "bearish" if score < -2 else "neutral"


async def fetch_yahoo_rss_sentiment(ticker: str) -> Dict[str, Any]:
    feed = feedparser.parse(f"https://feeds.finance.yahoo.com/rss/2.0/headline?s={ticker}&region=US&lang=en-US")
    headlines = [e.get("title", "") for e in feed.entries[:10]]
    score = _score_headlines(headlines)
    return {"ticker": ticker, "provider": "yahoo_rss", "overall": _overall(score), "score": score, "headlines": headlines[:5]}


async def fetch_alpha_vantage_sentiment(ticker: str, asset_type: str = "stock") -> Dict[str, Any]:
    api_key = os.getenv("ALPHA_VANTAGE_API_KEY", "")
    if not api_key:
        raise RuntimeError("ALPHA_VANTAGE_API_KEY is not configured")
    symbol = ticker.upper()
    # Alpha Vantage expects crypto topics differently sometimes, but ticker-only works for many symbols.
    params = {
        "function": "NEWS_SENTIMENT",
        "tickers": symbol,
        "sort": "LATEST",
        "limit": "20",
        "apikey": api_key,
    }
    async with httpx.AsyncClient(timeout=12) as client:
        r = await client.get("https://www.alphavantage.co/query", params=params)
        r.raise_for_status()
        data = r.json()
    feed = data.get("feed") or []
    headlines = [x.get("title", "") for x in feed[:10] if x.get("title")]
    relevance_items = []
    scores = []
    for item in feed:
        for ts in item.get("ticker_sentiment", []) or []:
            if ts.get("ticker", "").upper() == symbol:
                try:
                    scores.append(float(ts.get("ticker_sentiment_score", 0)))
                    relevance_items.append(ts)
                except Exception:
                    pass
    if scores:
        avg = sum(scores) / len(scores)
        score = round(avg * 10, 3)
    else:
        score = _score_headlines(headlines)
    return {
        "ticker": ticker,
        "asset_type": asset_type,
        "provider": "alpha_vantage",
        "overall": _overall(score),
        "score": score,
        "headlines": headlines[:5],
        "articles": feed[:10],
        "raw_provider_message": data.get("Information") or data.get("Note") or "",
    }


async def get_news_sentiment(ticker: str, asset_type: str = "stock") -> Dict[str, Any]:
    provider = os.getenv("NEWS_SENTIMENT_PROVIDER", "alpha_vantage").lower()
    if provider in {"alpha", "alphavantage", "alpha_vantage"}:
        try:
            return await fetch_alpha_vantage_sentiment(ticker, asset_type)
        except Exception as e:
            fallback = await fetch_yahoo_rss_sentiment(ticker)
            fallback["provider_error"] = str(e)
            fallback["provider"] = "yahoo_rss_fallback"
            return fallback
    return await fetch_yahoo_rss_sentiment(ticker)
