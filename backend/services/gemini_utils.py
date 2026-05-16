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


def get_gemini_api_key() -> str:
    # Accept common misspellings/aliases used in deployment dashboards.
    return (
        os.getenv("GEMINI_API_KEY")
        or os.getenv("GEMINY_API_KEY")
        or os.getenv("GOOGLE_API_KEY")
        or os.getenv("GOOGLE_GEMINI_API_KEY")
        or ""
    ).strip()


def gemini_available() -> bool:
    return bool(get_gemini_api_key())


def get_model():
    genai.configure(api_key=get_gemini_api_key())
    return genai.GenerativeModel(os.getenv("GEMINI_MODEL", "gemini-1.5-flash"))


def parse_json_object(text: str, fallback: Dict[str, Any]) -> Dict[str, Any]:
    try:
        return json.loads(text)
    except Exception:
        pass
    match = re.search(r"\{.*\}", text or "", re.S)
    if not match:
        return dict(fallback)
    try:
        return json.loads(match.group())
    except Exception:
        return dict(fallback)


def clamp_number(value: Any, low: float, high: float, default: float) -> float:
    try:
        v = float(value)
    except Exception:
        v = default
    return max(low, min(high, v))


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
