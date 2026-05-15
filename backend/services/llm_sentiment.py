"""
LLM-based news sentiment via Gemini.
Replaces simple keyword matching with semantic understanding.
"""
import os, json, re, asyncio, feedparser
import google.generativeai as genai
from datetime import datetime
from database import db
from dotenv import load_dotenv
from services.logger import child as _child_log
_log = _child_log('llm_sentiment')
load_dotenv()

genai.configure(api_key=os.getenv("GEMINI_API_KEY",""))
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
            return [e.get("title","") for e in feed.entries[:limit]]
        except: return []
    return await loop.run_in_executor(None, _fetch)

async def score_headline_llm(ticker, headline):
    try:
        model = genai.GenerativeModel("gemini-1.5-flash")
        prompt = f"""Rate the sentiment of this headline for {ticker} on scale -1.0 (very bearish) to +1.0 (very bullish):
"{headline}"
Reply ONLY with JSON: {{"score": 0.0, "reasoning": "brief"}}"""
        resp = model.generate_content(prompt)
        text = resp.text.strip()
        match = re.search(r'\{[^}]+\}', text)
        if match:
            data = json.loads(match.group())
            return {"headline":headline,"score":float(data.get("score",0)),"reasoning":data.get("reasoning","")}
    except Exception as _e: _log.debug(f"ignored: {_e}")
    return {"headline":headline,"score":0.0,"reasoning":"LLM unavailable"}

async def get_llm_sentiment(ticker, atype="stock", use_cache=True):
    cache_key = f"{ticker}_{atype}"
    if use_cache:
        cached = await sent_col.find_one({"_id":cache_key})
        if cached:
            try:
                age = (datetime.now() - datetime.fromisoformat(cached["timestamp"])).total_seconds()
                if age < 1800:  # 30 min cache
                    cached.pop("_id",None); return {**cached,"cached":True}
            except Exception as _e: _log.debug(f"ignored: {_e}")
    headlines = await fetch_headlines(ticker, atype, limit=8)
    if not headlines:
        return {"ticker":ticker,"overall_score":0,"signal":"NEUTRAL","reason":"No headlines","headlines":[]}
    # Score top 5 to save API calls
    tasks = [score_headline_llm(ticker, h) for h in headlines[:5]]
    scored = await asyncio.gather(*tasks)
    avg_score = sum(s["score"] for s in scored) / len(scored)
    if avg_score >= 0.4: sig,score,reason = "BUY",+2,f"Strong bullish sentiment ({avg_score:+.2f})"
    elif avg_score >= 0.15: sig,score,reason = "WEAK BUY",+1,f"Mild bullish sentiment ({avg_score:+.2f})"
    elif avg_score <= -0.4: sig,score,reason = "SELL",-2,f"Strong bearish sentiment ({avg_score:+.2f})"
    elif avg_score <= -0.15: sig,score,reason = "WEAK SELL",-1,f"Mild bearish sentiment ({avg_score:+.2f})"
    else: sig,score,reason = "NEUTRAL",0,f"Neutral sentiment ({avg_score:+.2f})"
    result = {"ticker":ticker,"overall_score":round(avg_score,3),"signal":sig,"score":score,
              "reason":reason,"headlines":scored,"count":len(scored),
              "indicator":"LLM_SENTIMENT","timestamp":datetime.now().isoformat()}
    await sent_col.replace_one({"_id":cache_key},{"_id":cache_key,**result},upsert=True)
    return result
