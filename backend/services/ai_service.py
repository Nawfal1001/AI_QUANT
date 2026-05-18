from dotenv import load_dotenv

from services.ai_quota_guard import (
    cache_ttl_seconds,
    can_call_ai,
    get_cached,
    guarded_fallback,
    is_quota_error,
    make_key,
    mark_call,
    set_cached,
    trigger_cooldown,
)
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

    cache_key = make_key("signal", ticker, atype)
    cached = get_cached(cache_key)
    if cached:
        return {**cached, "ai_cached": True}

    allowed, reason = can_call_ai()
    if not allowed:
        return guarded_fallback(fallback, reason, cached)

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
        mark_call()
        payload = _bounded_signal_payload(parse_json_object(response.text, fallback))
        return set_cached(cache_key, payload, cache_ttl_seconds("signal"))
    except Exception as e:
        if is_quota_error(e):
            trigger_cooldown(str(e))
        _log.warning(f"get_ai_signal failed for {ticker}: {e}")
        return guarded_fallback({**fallback, "reason": f"AI error: {str(e)[:120]}"}, str(e), cached)


async def get_ai_research(query, ticker=None, atype="stock"):
    fallback = {"response": "AI unavailable", "query": query, "ticker": ticker}
    if not gemini_available():
        return {"response": "AI unavailable: GEMINI_API_KEY not configured", "query": query, "ticker": ticker}

    cache_key = make_key("research", query, ticker, atype)
    cached = get_cached(cache_key)
    if cached:
        return {**cached, "ai_cached": True}

    allowed, reason = can_call_ai()
    if not allowed:
        return guarded_fallback(fallback, reason, cached)

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
        mark_call()
        payload = {"response": response.text, "query": query, "ticker": ticker}
        return set_cached(cache_key, payload, cache_ttl_seconds("research"))
    except Exception as e:
        if is_quota_error(e):
            trigger_cooldown(str(e))
        return guarded_fallback({"response": f"AI unavailable: {e}", "query": query, "ticker": ticker}, str(e), cached)
