import json
import os
import re

import google.generativeai as genai
from dotenv import load_dotenv

load_dotenv()


def _configure():
    genai.configure(api_key=os.getenv("GEMINI_API_KEY", ""))


def _safe_json(text, fallback):
    try:
        return json.loads(text)
    except Exception:
        pass
    match = re.search(r"\{.*\}", text or "", re.S)
    if not match:
        return fallback
    try:
        return json.loads(match.group())
    except Exception:
        return fallback


def _bounded_signal_payload(payload):
    try:
        score = int(payload.get("score", 0))
    except Exception:
        score = 0
    try:
        confidence = int(payload.get("confidence", 50))
    except Exception:
        confidence = 50
    return {
        "score": max(-1, min(1, score)),
        "confidence": max(0, min(100, confidence)),
        "reason": str(payload.get("reason", "AI analysis"))[:300],
        "time_horizon": str(payload.get("time_horizon", "short_term"))[:50],
        "risk_flags": payload.get("risk_flags", []) if isinstance(payload.get("risk_flags", []), list) else [],
    }


async def get_ai_signal(ticker, atype):
    fallback = {"score": 0, "reason": "AI unavailable", "confidence": 50, "time_horizon": "short_term", "risk_flags": []}
    if not os.getenv("GEMINI_API_KEY"):
        return fallback
    try:
        _configure()
        model = genai.GenerativeModel(os.getenv("GEMINI_MODEL", "gemini-1.5-flash"))
        prompt = f"""
You are a bounded trading sentiment classifier for an existing trading platform.
You do NOT place trades, do NOT create orders, and do NOT override risk controls.
Classify only the short-term directional sentiment for the provided asset.

Asset:
- ticker: {ticker}
- asset_type: {atype}

Return JSON only. No markdown. No extra text.
Schema:
{{
  "score": -1 | 0 | 1,
  "confidence": 0-100,
  "time_horizon": "intraday|short_term|swing",
  "risk_flags": ["string"],
  "reason": "one short reason under 25 words"
}}
Rules:
- score=1 means bullish, -1 bearish, 0 neutral/unclear.
- Use confidence above 75 only when evidence is strong and not conflicting.
- Use score=0 if data is insufficient or ambiguous.
"""
        response = model.generate_content(prompt)
        return _bounded_signal_payload(_safe_json(response.text, fallback))
    except Exception:
        return fallback


async def get_ai_research(query, ticker=None, atype="stock"):
    if not os.getenv("GEMINI_API_KEY"):
        return {"response": "AI unavailable: GEMINI_API_KEY not configured", "query": query, "ticker": ticker}
    try:
        _configure()
        model = genai.GenerativeModel(os.getenv("GEMINI_MODEL", "gemini-1.5-flash"))
        prompt = f"""
You are a trading research assistant. Provide analytical research only.
Do not give guarantees. Do not tell the user to place a trade. Include uncertainty and risk factors.

Request: {query}
Asset: {ticker or "not specified"}
Asset type: {atype}

Return concise structured text with:
1. Market context
2. Bull case
3. Bear case
4. Key risks
5. What data would confirm or invalidate the view
"""
        response = model.generate_content(prompt)
        return {"response": response.text, "query": query, "ticker": ticker}
    except Exception as e:
        return {"response": f"AI unavailable: {e}", "query": query}
