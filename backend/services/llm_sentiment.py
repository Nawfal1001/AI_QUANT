"""LLM-based news sentiment via Gemini with strict JSON guardrails."""
import asyncio
from datetime import datetime

import feedparser

from database import db
from services.gemini_utils import clamp_number, gemini_available, get_model, json_only_guardrails, parse_json_object
from services.logger import child as _child_log

_log = _child_log('llm_sentiment')
sent_col = db["llm_sentiment_cache"]


async def fetch_headlines(ticker, atype="stock", limit=10):
    loop = asyncio.get_event_loop()

    def _fetch():
        try:
            if atype == "stock":
                url = f"https://feeds.finance.yahoo.com/rss/2.0/headline?s={ticker}&region=US&lang=en-US"
            else:
                url = "https://cointelegraph.com/rss"
            feed = feedparser.parse(url)
            return [e.get("title", "") for e in feed.entries[:limit]]
        except Exception:
            return []

    return await loop.run_in_executor(None, _fetch)


async def score_headline_llm(ticker, headline):
    fallback = {"score": 0.0, "reasoning": "LLM unavailable"}
    if not gemini_available():
        return {"headline": headline, **fallback}
    try:
        model = get_model()
        schema = '{"score": -1.0 to 1.0, "reasoning": "under 20 words"}'
        rules = """
- Score sentiment impact of this headline on the specified asset.
- Use 0.0 if impact is unclear, mixed, or irrelevant.
- Use absolute score above 0.7 only for strongly material headlines.
"""
        prompt = json_only_guardrails("score the sentiment impact of one news headline", schema, rules)
        prompt += f"\n\nAsset: {ticker}\nHeadline: {headline}"
        resp = model.generate_content(prompt)
        data = parse_json_object(resp.text, fallback)
        return {
            "headline": headline,
            "score": round(clamp_number(data.get("score", 0.0), -1.0, 1.0, 0.0), 4),
            "reasoning": str(data.get("reasoning", "AI analysis"))[:200],
        }
    except Exception as e:
        _log.debug(f"ignored: {e}")
        return {"headline": headline, **fallback}


async def get_llm_sentiment(ticker, atype="stock", use_cache=True):
    cache_key = f"{ticker}_{atype}"
    if use_cache:
        cached = await sent_col.find_one({"_id": cache_key})
        if cached:
            try:
                age = (datetime.now() - datetime.fromisoformat(cached["timestamp"])).total_seconds()
                if age < 1800:
                    cached.pop("_id", None)
                    return {**cached, "cached": True}
            except Exception as e:
                _log.debug(f"ignored: {e}")

    headlines = await fetch_headlines(ticker, atype, limit=8)
    if not headlines:
        return {"ticker": ticker, "overall_score": 0, "signal": "NEUTRAL", "reason": "No headlines", "headlines": []}

    scored = await asyncio.gather(*[score_headline_llm(ticker, h) for h in headlines[:5]])
    avg_score = sum(s["score"] for s in scored) / len(scored)

    if avg_score >= 0.4:
        sig, score, reason = "BUY", +2, f"Strong bullish sentiment ({avg_score:+.2f})"
    elif avg_score >= 0.15:
        sig, score, reason = "WEAK BUY", +1, f"Mild bullish sentiment ({avg_score:+.2f})"
    elif avg_score <= -0.4:
        sig, score, reason = "SELL", -2, f"Strong bearish sentiment ({avg_score:+.2f})"
    elif avg_score <= -0.15:
        sig, score, reason = "WEAK SELL", -1, f"Mild bearish sentiment ({avg_score:+.2f})"
    else:
        sig, score, reason = "NEUTRAL", 0, f"Neutral sentiment ({avg_score:+.2f})"

    result = {
        "ticker": ticker,
        "overall_score": round(avg_score, 3),
        "signal": sig,
        "score": score,
        "reason": reason,
        "headlines": scored,
        "count": len(scored),
        "indicator": "LLM_SENTIMENT",
        "timestamp": datetime.now().isoformat(),
    }
    await sent_col.replace_one({"_id": cache_key}, {"_id": cache_key, **result}, upsert=True)
    return result
