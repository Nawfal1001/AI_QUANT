from dotenv import load_dotenv

from services.gemini_utils import clamp_number, gemini_available, get_model, json_only_guardrails, parse_json_object
from services.logger import child as _child_log

_log = _child_log("ai_service")

load_dotenv()


def _bounded_signal_payload(payload):
    return {
        "score": int(clamp_number(payload.get("score", 0), -1, 1, 0)),
        "confidence": int(clamp_number(payload.get("confidence", 50), 0, 100, 50)),
        "reason": str(payload.get("reason", "AI analysis"))[:300],
        "time_horizon": str(payload.get("time_horizon", "short_term"))[:50],
        "risk_flags": payload.get("risk_flags", []) if isinstance(payload.get("risk_flags", []), list) else [],
    }


async def get_ai_signal(ticker, atype):
    fallback = {"score": 0, "reason": "AI unavailable", "confidence": 50, "time_horizon": "short_term", "risk_flags": []}
    if not gemini_available():
        return {**fallback, "reason": "AI unavailable: GEMINI_API_KEY not configured"}
    try:
        model = get_model()
        schema = '{"score": -1|0|1, "confidence": 0-100, "time_horizon": "intraday|short_term|swing", "risk_flags": ["string"], "reason": "under 25 words"}'
        rules = """
- score=1 means bullish, -1 bearish, 0 neutral/unclear.
- Use confidence above 75 only when evidence is strong, recent, and non-conflicting.
- Use score=0 if data is insufficient, stale, or ambiguous.
- This is sentiment classification only, not a trade recommendation.
"""
        prompt = json_only_guardrails("classify short-term directional sentiment for one asset", schema, rules)
        prompt += f"\n\nAsset JSON: {{\"ticker\": \"{ticker}\", \"asset_type\": \"{atype}\"}}"
        response = model.generate_content(prompt)
        return _bounded_signal_payload(parse_json_object(response.text, fallback))
    except Exception as e:
        _log.warning(f"get_ai_signal failed for {ticker}: {e}")
        return {**fallback, "reason": f"AI error: {str(e)[:120]}"}


async def get_ai_research(query, ticker=None, atype="stock"):
    if not gemini_available():
        return {"response": "AI unavailable: GEMINI_API_KEY not configured", "query": query, "ticker": ticker}
    try:
        model = get_model()
        prompt = """
You are a financial-market research assistant. Provide analytical research only.
Do not give guarantees. Do not tell the user to place a trade. Include uncertainty and risk factors.
Avoid inventing unavailable facts. If data is missing, say what is missing.

Return concise structured text with:
1. Market context
2. Bull case
3. Bear case
4. Key risks
5. What data would confirm or invalidate the view
"""
        prompt += f"\n\nRequest: {query}\nAsset: {ticker or 'not specified'}\nAsset type: {atype}"
        response = model.generate_content(prompt)
        return {"response": response.text, "query": query, "ticker": ticker}
    except Exception as e:
        return {"response": f"AI unavailable: {e}", "query": query}
