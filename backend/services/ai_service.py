import os, google.generativeai as genai
from dotenv import load_dotenv
load_dotenv()
genai.configure(api_key=os.getenv("GEMINI_API_KEY",""))

async def get_ai_signal(ticker, atype):
    try:
        m = genai.GenerativeModel("gemini-1.5-flash")
        prompt = (
            f"Rate {ticker} ({atype}) sentiment: bullish(+1), neutral(0), bearish(-1). "
            'Reply JSON only: {"score":0,"reason":"","confidence":50}'
        )
        r = m.generate_content(prompt)
        import json, re
        t = r.text
        mt = re.search(r"\{[^}]+\}", t)
        if mt:
            return json.loads(mt.group())
        return {"score": 0, "reason": "AI analysis", "confidence": 50}
    except:
        return {"score": 0, "reason": "AI unavailable", "confidence": 50}

async def get_ai_research(query, ticker=None, atype="stock"):
    try:
        m = genai.GenerativeModel("gemini-1.5-flash")
        prompt = f"Trading analysis: {query}" + (f" for {ticker} ({atype})" if ticker else "")
        r = m.generate_content(prompt)
        return {"response": r.text, "query": query, "ticker": ticker}
    except Exception as e:
        return {"response": f"AI unavailable: {e}", "query": query}
