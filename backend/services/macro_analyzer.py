"""
Macro Impact Analyzer.

Interprets macro/news events and converts them into cross-asset directional bias.
Designed to connect Fed/CPI/NFP/ECB/geopolitical/oil news to assets such as:
- USD / forex pairs
- Gold / XAUUSD
- US equities
- crypto / BTC / ETH
- oil

This service does not place orders. It returns bias and confidence that the bot
runner can use to boost, reduce, or block signals.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

import feedparser

from database import db
from services.logger import child

log = child("macro_analyzer")

col_macro_cache = db["macro_impact_cache"]
col_macro_events = db["macro_impact_events"]

MACRO_FEEDS = [
    "https://feeds.finance.yahoo.com/rss/2.0/headline?s=%5EDJI,%5EGSPC,%5EIXIC,GC=F,DX-Y.NYB,CL=F,BTC-USD&region=US&lang=en-US",
    "https://www.investing.com/rss/news_25.rss",
    "https://www.investing.com/rss/news_1.rss",
]

EVENT_KEYWORDS = {
    "FOMC": ["fomc", "federal reserve", "fed", "powell", "rate decision", "interest rates"],
    "CPI": ["cpi", "inflation", "consumer price"],
    "PPI": ["ppi", "producer price"],
    "NFP": ["nonfarm", "payrolls", "jobs report", "unemployment"],
    "ECB": ["ecb", "lagarde", "european central bank"],
    "BOE": ["boe", "bank of england"],
    "BOJ": ["boj", "bank of japan", "yen intervention"],
    "GDP": ["gdp", "growth data"],
    "OIL": ["oil", "opec", "crude", "inventory", "supply"],
    "GEOPOLITICAL": ["war", "attack", "sanction", "geopolitical", "missile", "conflict"],
}

HAWKISH_WORDS = ["hawkish", "higher for longer", "rate hike", "hikes", "tightening", "hot inflation", "above forecast", "strong jobs", "sticky inflation"]
DOVISH_WORDS = ["dovish", "rate cut", "cuts", "easing", "cooling inflation", "below forecast", "weak jobs", "soft landing", "slowing"]
RISK_OFF_WORDS = ["risk off", "selloff", "recession", "crisis", "panic", "war", "conflict", "default", "banking stress"]
RISK_ON_WORDS = ["risk on", "rally", "optimism", "soft landing", "stimulus", "cooling inflation", "rate cuts"]

ASSET_ALIASES = {
    "DXY": "USD", "USD": "USD", "UUP": "USD",
    "XAUUSD": "GOLD", "GC": "GOLD", "GC=F": "GOLD", "GOLD": "GOLD", "GLD": "GOLD",
    "BTC": "CRYPTO", "BTCUSD": "CRYPTO", "BTC-USD": "CRYPTO", "ETH": "CRYPTO", "ETHUSD": "CRYPTO", "SOL": "CRYPTO",
    "SPY": "EQUITIES", "QQQ": "EQUITIES", "DIA": "EQUITIES", "IWM": "EQUITIES", "NVDA": "EQUITIES", "AAPL": "EQUITIES", "TSLA": "EQUITIES",
    "CL": "OIL", "CL=F": "OIL", "USO": "OIL", "OIL": "OIL",
}


def _now_iso() -> str:
    return datetime.utcnow().isoformat()


def _direction_to_score(direction: str, confidence: float) -> float:
    d = (direction or "neutral").lower()
    if d == "bullish":
        return confidence
    if d == "bearish":
        return -confidence
    return 0.0


def _safe_json(text: str) -> Optional[Dict[str, Any]]:
    try:
        return json.loads(text)
    except Exception:
        pass
    m = re.search(r"\{.*\}", text or "", flags=re.S)
    if not m:
        return None
    try:
        return json.loads(m.group())
    except Exception:
        return None


def _detect_event_type(text: str) -> str:
    low = text.lower()
    for event, words in EVENT_KEYWORDS.items():
        if any(w in low for w in words):
            return event
    return "GENERAL_MACRO"


def _rule_based_macro_analysis(headlines: List[str]) -> Dict[str, Any]:
    text = "\n".join(headlines).lower()
    event_type = _detect_event_type(text)
    hawkish = sum(1 for w in HAWKISH_WORDS if w in text)
    dovish = sum(1 for w in DOVISH_WORDS if w in text)
    risk_off = sum(1 for w in RISK_OFF_WORDS if w in text)
    risk_on = sum(1 for w in RISK_ON_WORDS if w in text)

    surprise = "neutral"
    if hawkish > dovish:
        surprise = "hawkish"
    elif dovish > hawkish:
        surprise = "dovish"

    risk_mode = "neutral"
    if risk_off > risk_on:
        risk_mode = "risk_off"
    elif risk_on > risk_off:
        risk_mode = "risk_on"

    bias = {
        "USD": {"direction": "neutral", "confidence": 50, "reason": "neutral macro"},
        "GOLD": {"direction": "neutral", "confidence": 45, "reason": "neutral macro"},
        "EQUITIES": {"direction": "neutral", "confidence": 45, "reason": "neutral macro"},
        "CRYPTO": {"direction": "neutral", "confidence": 45, "reason": "neutral macro"},
        "OIL": {"direction": "neutral", "confidence": 40, "reason": "neutral macro"},
    }

    if surprise == "hawkish":
        bias.update({
            "USD": {"direction": "bullish", "confidence": 72, "reason": "hawkish policy usually supports USD"},
            "GOLD": {"direction": "bearish", "confidence": 62, "reason": "higher real-rate expectations pressure gold"},
            "EQUITIES": {"direction": "bearish", "confidence": 64, "reason": "higher rates pressure risk assets"},
            "CRYPTO": {"direction": "bearish", "confidence": 66, "reason": "hawkish liquidity shock usually pressures crypto"},
        })
    elif surprise == "dovish":
        bias.update({
            "USD": {"direction": "bearish", "confidence": 68, "reason": "dovish policy usually weakens USD"},
            "GOLD": {"direction": "bullish", "confidence": 64, "reason": "lower-rate expectations support gold"},
            "EQUITIES": {"direction": "bullish", "confidence": 62, "reason": "lower-rate expectations support risk assets"},
            "CRYPTO": {"direction": "bullish", "confidence": 66, "reason": "dovish liquidity expectations support crypto"},
        })

    if risk_mode == "risk_off":
        bias["USD"] = {"direction": "bullish", "confidence": max(70, bias["USD"]["confidence"]), "reason": "risk-off safe-haven demand"}
        bias["EQUITIES"] = {"direction": "bearish", "confidence": 72, "reason": "risk-off pressure"}
        bias["CRYPTO"] = {"direction": "bearish", "confidence": 74, "reason": "risk-off usually hurts crypto beta"}
        bias["GOLD"] = {"direction": "bullish", "confidence": 58, "reason": "safe-haven bid can support gold despite USD strength"}
    elif risk_mode == "risk_on":
        bias["EQUITIES"] = {"direction": "bullish", "confidence": 68, "reason": "risk-on flow"}
        bias["CRYPTO"] = {"direction": "bullish", "confidence": 70, "reason": "risk-on flow supports crypto"}

    return {
        "event_type": event_type,
        "surprise": surprise,
        "risk_mode": risk_mode,
        "asset_bias": bias,
        "confidence": max([v.get("confidence", 0) for v in bias.values()] or [50]),
        "reason": f"rule-based macro read: event={event_type}, surprise={surprise}, risk_mode={risk_mode}",
        "headlines": headlines[:10],
        "source": "rules",
        "created_at": _now_iso(),
    }


async def fetch_macro_headlines(limit: int = 20) -> List[str]:
    cache = await col_macro_cache.find_one({"kind": "macro_headlines"})
    if cache:
        ts = datetime.fromisoformat(cache.get("updated_at"))
        if datetime.utcnow() - ts < timedelta(minutes=15):
            return cache.get("headlines", [])[:limit]

    def _fetch() -> List[str]:
        out: List[str] = []
        for url in MACRO_FEEDS:
            try:
                feed = feedparser.parse(url)
                out.extend([e.get("title", "") for e in feed.entries[:12] if e.get("title")])
            except Exception:
                continue
        seen = []
        for h in out:
            if h and h not in seen:
                seen.append(h)
        return seen[:limit]

    loop = asyncio.get_event_loop()
    headlines = await loop.run_in_executor(None, _fetch)
    await col_macro_cache.replace_one(
        {"kind": "macro_headlines"},
        {"kind": "macro_headlines", "headlines": headlines, "updated_at": _now_iso()},
        upsert=True,
    )
    return headlines[:limit]


async def analyze_macro_impact(headlines: Optional[List[str]] = None, use_ai: bool = True) -> Dict[str, Any]:
    """Analyze macro headlines and return cross-asset impact map."""
    if headlines is None:
        headlines = await fetch_macro_headlines()

    base = _rule_based_macro_analysis(headlines)
    if not use_ai or not os.getenv("GEMINI_API_KEY"):
        await col_macro_events.insert_one(dict(base))
        return base

    try:
        import google.generativeai as genai
        genai.configure(api_key=os.getenv("GEMINI_API_KEY", ""))
        model = genai.GenerativeModel("gemini-1.5-flash")
        prompt = f"""
You are a macro trading analyst. Analyze these headlines and infer likely cross-asset flows.
Return JSON only with this exact shape:
{{
  "event_type":"FOMC|CPI|NFP|ECB|BOJ|OIL|GEOPOLITICAL|GENERAL_MACRO",
  "surprise":"hawkish|dovish|inflationary|deflationary|growth_positive|growth_negative|neutral",
  "risk_mode":"risk_on|risk_off|neutral",
  "asset_bias":{{
    "USD":{{"direction":"bullish|bearish|neutral","confidence":0,"reason":""}},
    "GOLD":{{"direction":"bullish|bearish|neutral","confidence":0,"reason":""}},
    "EQUITIES":{{"direction":"bullish|bearish|neutral","confidence":0,"reason":""}},
    "CRYPTO":{{"direction":"bullish|bearish|neutral","confidence":0,"reason":""}},
    "OIL":{{"direction":"bullish|bearish|neutral","confidence":0,"reason":""}}
  }},
  "confidence":0,
  "reason":"short macro explanation"
}}
Headlines:
{chr(10).join('- ' + h for h in headlines[:15])}
"""
        response = model.generate_content(prompt)
        parsed = _safe_json(response.text)
        if parsed and isinstance(parsed.get("asset_bias"), dict):
            parsed["headlines"] = headlines[:10]
            parsed["source"] = "ai+rules"
            parsed["created_at"] = _now_iso()
            await col_macro_events.insert_one(dict(parsed))
            return parsed
    except Exception as e:
        log.warning(f"AI macro analysis failed, using rules: {e}")

    await col_macro_events.insert_one(dict(base))
    return base


def asset_bucket_for_symbol(ticker: str, asset_type: str = "") -> str:
    t = (ticker or "").upper().replace("/", "").replace("-", "_")
    if t in ASSET_ALIASES:
        return ASSET_ALIASES[t]
    if asset_type == "crypto":
        return "CRYPTO"
    if asset_type == "stock":
        return "EQUITIES"
    if asset_type == "forex":
        if "USD" in t:
            return "USD"
        return "FOREX"
    if asset_type in {"gold", "metal"}:
        return "GOLD"
    if asset_type == "oil":
        return "OIL"
    return "UNKNOWN"


def macro_bias_for_symbol(macro: Dict[str, Any], ticker: str, asset_type: str = "") -> Dict[str, Any]:
    bucket = asset_bucket_for_symbol(ticker, asset_type)
    bias = (macro.get("asset_bias") or {}).get(bucket)
    if not bias:
        return {"bucket": bucket, "direction": "neutral", "confidence": 0, "score": 0, "reason": "no macro bias"}
    direction = bias.get("direction", "neutral")
    confidence = float(bias.get("confidence", 0) or 0)
    return {"bucket": bucket, "direction": direction, "confidence": confidence, "score": _direction_to_score(direction, confidence), "reason": bias.get("reason", "")}


def adjust_signal_with_macro(signal: Dict[str, Any], macro_bias: Dict[str, Any], max_adjustment: float = 18.0) -> Dict[str, Any]:
    """Adjust a generated BUY/SELL/HOLD signal using macro bias."""
    out = dict(signal or {})
    signal_str = str(out.get("signal", "HOLD")).upper()
    confidence = float(out.get("confidence", 0) or 0)
    direction = macro_bias.get("direction", "neutral")
    macro_conf = float(macro_bias.get("confidence", 0) or 0)
    adj = min(max_adjustment, macro_conf * 0.22)

    if "BUY" in signal_str:
        if direction == "bullish":
            confidence += adj
            action = "boost"
        elif direction == "bearish":
            confidence -= adj
            action = "reduce"
        else:
            action = "neutral"
    elif "SELL" in signal_str:
        if direction == "bearish":
            confidence += adj
            action = "boost"
        elif direction == "bullish":
            confidence -= adj
            action = "reduce"
        else:
            action = "neutral"
    else:
        action = "neutral"

    confidence = max(0.0, min(100.0, confidence))
    out["confidence"] = round(confidence, 2)
    out["macro"] = {**macro_bias, "adjustment_action": action, "confidence_adjustment": round(adj if action == "boost" else -adj if action == "reduce" else 0, 2)}
    if action == "reduce" and macro_conf >= 75 and confidence < 50:
        out["signal"] = "HOLD"
        out["reason"] = f"macro conflict blocked signal: {macro_bias.get('reason', '')}; {out.get('reason', '')}".strip()
    return out


async def analyze_macro_report(
    event_name: str,
    report_text: str,
    market_reaction: Optional[Dict[str, Any]] = None,
    use_ai: bool = True,
) -> Dict[str, Any]:
    """Analyze a single macro release (CPI, NFP, FOMC, etc.) and return cross-asset bias.

    Treats the report_text as the canonical headline pool, optionally enriched with
    market_reaction context. Reuses analyze_macro_impact so callers get the same
    asset_bias shape (USD/GOLD/EQUITIES/CRYPTO/OIL).
    """
    headlines = [event_name] if event_name else []
    if report_text:
        for line in str(report_text).splitlines():
            line = line.strip()
            if line:
                headlines.append(line)
    if market_reaction:
        for k, v in market_reaction.items():
            headlines.append(f"{k}: {v}")
    macro = await analyze_macro_impact(headlines=headlines, use_ai=use_ai)
    macro["event_name"] = event_name
    macro.setdefault("needs_price_confirmation", True)
    macro.setdefault("time_horizon", "intraday")
    macro.setdefault("trade_instruction", "Follow asset_bias with price confirmation around the release.")
    return macro


async def macro_adjust_signal(ticker: str, asset_type: str, signal: Dict[str, Any], use_ai: bool = True) -> Dict[str, Any]:
    macro = await analyze_macro_impact(use_ai=use_ai)
    bias = macro_bias_for_symbol(macro, ticker, asset_type)
    adjusted = adjust_signal_with_macro(signal, bias)
    adjusted["macro_context"] = {"event_type": macro.get("event_type"), "risk_mode": macro.get("risk_mode"), "surprise": macro.get("surprise"), "confidence": macro.get("confidence"), "source": macro.get("source")}
    return adjusted
