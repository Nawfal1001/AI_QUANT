"""Shared Gemini helpers for strict prompts and safe JSON parsing."""
import json
import os
import re
from typing import Any, Dict

import google.generativeai as genai

TRADING_EXPERT_SYSTEM = """
You are an institutional-grade trading analyst and market-structure expert.
Use broad expertise across equities, crypto, forex, commodities, rates, macroeconomics,
central banks, inflation, liquidity, derivatives, positioning, correlations, volatility,
news impact, cross-asset flows, risk-on/risk-off regimes, and technical market structure.

Think like a professional desk analyst:
- Separate signal from noise.
- Prefer recent, confirmed, multi-source evidence.
- Consider macro regime, liquidity, volatility, correlations, and positioning.
- Identify when a move is crowded, fragile, news-driven, or unsupported by volume.
- Detect conflicts between price action, sentiment, derivatives, and macro context.
- Explicitly reduce confidence when evidence is stale, missing, conflicting, or ambiguous.
- Never pretend to have live data unless the provided input includes it.
""".strip()

DEFAULT_GEMINI_MODEL = "gemini-1.5-flash-latest"
SAFE_FALLBACK_MODELS = ["gemini-1.5-flash-latest", "gemini-1.5-flash-002", "gemini-1.5-flash", "gemini-1.0-pro"]
PRO_MODEL_ALIASES = {"gemini-pro", "gemini-1.0-pro", "gemini-1.5-pro", "models/gemini-pro", "models/gemini-1.0-pro", "models/gemini-1.5-pro"}

def get_gemini_api_key() -> str:
    return (os.getenv("GEMINI_API_KEY") or os.getenv("GEMINY_API_KEY") or os.getenv("GOOGLE_API_KEY") or os.getenv("GOOGLE_GEMINI_API_KEY") or "").strip()

def _clean_model_name(name: str) -> str:
    name=(name or "").strip()
    if name.startswith("models/"): name=name.split("/",1)[1]
    if name in PRO_MODEL_ALIASES or name.endswith("-pro"): return DEFAULT_GEMINI_MODEL
    if name in {"gemini-1.5-flash", "models/gemini-1.5-flash"}: return DEFAULT_GEMINI_MODEL
    return name or DEFAULT_GEMINI_MODEL

def get_gemini_model_name() -> str:
    return _clean_model_name(os.getenv("GEMINI_MODEL") or os.getenv("GEMINY_MODEL") or DEFAULT_GEMINI_MODEL)

def get_model_name() -> str:
    return get_gemini_model_name()

def gemini_available() -> bool:
    return bool(get_gemini_api_key())

def get_model(model_name: str | None = None):
    genai.configure(api_key=get_gemini_api_key())
    return genai.GenerativeModel(_clean_model_name(model_name or get_gemini_model_name()))

def _is_model_not_found(err: Exception) -> bool:
    s=str(err).lower()
    return "404" in s or "not found" in s or "not supported for generatecontent" in s

def generate_content(prompt: str):
    """Generate with configured model, then safe fallbacks.
    Prevents stale GEMINI_MODEL=gemini-1.5-flash from breaking the app.
    """
    tried=[]
    first=get_gemini_model_name()
    for name in [first]+[m for m in SAFE_FALLBACK_MODELS if m!=first]:
        tried.append(name)
        try:
            return get_model(name).generate_content(prompt)
        except Exception as e:
            if not _is_model_not_found(e) or name==SAFE_FALLBACK_MODELS[-1]:
                raise
            continue

def ping() -> Dict[str, Any]:
    import time
    out={"available":False,"model":get_gemini_model_name(),"reason":"","latency_ms":0,"key_source":""}
    key=get_gemini_api_key()
    if not key:
        out["reason"]="GEMINI_API_KEY (or GEMINY_API_KEY / GOOGLE_API_KEY / GOOGLE_GEMINI_API_KEY) is not set"; return out
    for name in ("GEMINI_API_KEY","GEMINY_API_KEY","GOOGLE_API_KEY","GOOGLE_GEMINI_API_KEY"):
        if os.getenv(name,"").strip()==key: out["key_source"]=name; break
    try:
        t0=time.time(); resp=generate_content('Reply with the JSON: {"ok":true}'); out["latency_ms"]=int((time.time()-t0)*1000)
        text=(resp.text or "").strip(); out["available"]="ok" in text.lower() or "true" in text.lower(); out["reason"]="Connected" if out["available"] else f"Unexpected response: {text[:120]}"; out["model"]=get_gemini_model_name(); return out
    except Exception as e:
        out["reason"]=f"Gemini API error: {str(e)[:200]}"; return out

def parse_json_object(text: str, fallback: Dict[str, Any]) -> Dict[str, Any]:
    try: return json.loads(text)
    except Exception: pass
    match=re.search(r"\{.*\}", text or "", re.S)
    if not match: return dict(fallback)
    try: return json.loads(match.group())
    except Exception: return dict(fallback)

def clamp_number(value: Any, low: float, high: float, default: float) -> float:
    try: v=float(value)
    except Exception: v=default
    return max(low,min(high,v))

def json_only_guardrails(task: str, schema: str, rules: str = "") -> str:
    return f"""
{TRADING_EXPERT_SYSTEM}

Your current job is: {task}

Critical rules:
- Return valid JSON only. No markdown. No prose outside JSON.
- Use all provided structured data and financial expertise, but do not invent unavailable facts, prices, news, correlations, indicators, or events.
- If evidence is insufficient, stale, or conflicting, choose neutral/low confidence.
- Do not place trades, recommend position size, or override risk controls.
- Confidence must reflect evidence quality, not conviction style.
- Use high confidence only when evidence is strong, recent, multi-factor, and non-conflicting.
- Prefer calibrated, conservative outputs over dramatic predictions.

Required JSON schema:
{schema}

Additional task rules:
{rules}
""".strip()

def research_guardrails(task: str) -> str:
    return f"""
{TRADING_EXPERT_SYSTEM}

Your current job is: {task}

Rules:
- Provide expert financial analysis, not trade instructions.
- Do not guarantee outcomes.
- Distinguish confirmed facts from interpretation.
- Mention what data is missing when relevant.
- Always include both bullish and bearish interpretations when possible.
- Include market regime, macro/news impact, cross-asset context, and invalidation factors.
""".strip()
