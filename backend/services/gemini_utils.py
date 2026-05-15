"""Shared Gemini helpers for strict prompts and safe JSON parsing."""
import json
import os
import re
from typing import Any, Dict

import google.generativeai as genai


def gemini_available() -> bool:
    return bool(os.getenv("GEMINI_API_KEY", "").strip())


def get_model():
    genai.configure(api_key=os.getenv("GEMINI_API_KEY", ""))
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
You are a precise financial-market analysis component inside a trading platform.
Your job is: {task}

Critical rules:
- Return valid JSON only. No markdown. No prose outside JSON.
- Do not invent unavailable facts, prices, news, correlations, or indicators.
- If evidence is insufficient or conflicting, choose neutral/low confidence.
- Do not place trades, recommend position size, or override risk controls.
- Confidence must reflect evidence quality, not conviction style.
- Use high confidence only when evidence is strong, recent, and non-conflicting.

Required JSON schema:
{schema}

Additional task rules:
{rules}
""".strip()
