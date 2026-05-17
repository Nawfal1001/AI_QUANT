"""
AI commentary for economic calendar events using shared Gemini fallback utilities.
"""
from __future__ import annotations
import json
from datetime import datetime
from typing import Any, Dict
from database import db
from services.gemini_utils import gemini_available, get_model_name, generate_content, json_only_guardrails, parse_json_object, ping
from services.logger import child
log=child("calendar_ai"); col_events=db["economic_events"]; col_cache=db["calendar_ai_cache"]
def _now_iso(): return datetime.utcnow().isoformat()
def _briefing_key(event: Dict[str, Any], kind: str) -> str: return f"{event.get('event_id') or event.get('event_name')}::{kind}"
def _has_actual(event): return event.get("actual") not in (None,"","N/A")
def _event_label(event): return f"{event.get('event_name') or event.get('event_type') or 'Economic event'} ({event.get('currency') or event.get('country') or 'USD'}) @ {event.get('release_time') or ''}"
PRE_BRIEFING_SCHEMA='''{"summary":"1-sentence what-the-event-is","expected":"1-2 sentence what the market is pricing in","scenarios":[{"surprise":"hawkish_upside|dovish_downside|in_line","playbook":"1-2 sentence cross-asset reaction"}],"primary_assets":["USD","GOLD","EQUITIES","CRYPTO","OIL","RATES"],"watch_for":"subtle data point to focus on","confidence":0}'''
POST_BRIEFING_SCHEMA='''{"headline":"1-sentence what happened","surprise":"hawkish|dovish|inflationary|disinflationary|growth_positive|growth_negative|in_line","cross_asset":{"USD":"bullish|bearish|neutral","GOLD":"bullish|bearish|neutral","EQUITIES":"bullish|bearish|neutral","CRYPTO":"bullish|bearish|neutral","OIL":"bullish|bearish|neutral"},"playbook":"2-3 sentence what to do over next session","invalidation":"what would flip the read","confidence":0}'''
def _build_pre_prompt(event):
    prompt=json_only_guardrails("preview an upcoming economic release for traders",PRE_BRIEFING_SCHEMA,"Do not invent actual number. Output JSON only. Use forecast/previous only.")
    facts={k:event.get(k) for k in ["event_name","event_type","currency","country","release_time","impact","forecast","previous"]}
    return prompt+f"\n\nEvent JSON: {json.dumps(facts,default=str)[:6000]}"
def _build_post_prompt(event):
    prompt=json_only_guardrails("interpret a just-released economic print for traders",POST_BRIEFING_SCHEMA,"Anchor surprise to actual vs forecast and revisions. Output JSON only.")
    facts={k:event.get(k) for k in ["event_name","event_type","currency","country","release_time","impact","forecast","previous","actual","market_reaction"]}
    return prompt+f"\n\nEvent JSON: {json.dumps(facts,default=str)[:6000]}"
def _empty(kind, reason): return {"kind":kind,"available":False,"reason":reason,"model":get_model_name(),"generated_at":_now_iso()}
async def _generate(event, kind):
    if not gemini_available(): return _empty(kind,"AI unavailable: Gemini key not configured")
    try:
        p=ping()
        if not p.get("available"):
            return _empty(kind,f"Gemini ping failed: {p.get('reason')}")
        prompt=_build_pre_prompt(event) if kind=="pre" else _build_post_prompt(event)
        resp=generate_content(prompt); text=getattr(resp,"text","") or ""; data=parse_json_object(text,{})
        if not data: return _empty(kind,f"Gemini returned no JSON. Raw: {text[:120]}")
        return {"kind":kind,"available":True,"model":get_model_name(),"generated_at":_now_iso(),**data}
    except Exception as e:
        log.warning(f"calendar AI {kind} briefing failed for {_event_label(event)}: {e}"); return _empty(kind,f"Gemini error: {str(e)[:220]}")
async def get_briefing(event, use_cache=True):
    out={"event_id":event.get("event_id"),"pre":None,"post":None}
    pre_key=_briefing_key(event,"pre"); pre_cached=await col_cache.find_one({"_id":pre_key}) if use_cache else None
    if pre_cached and pre_cached.get("forecast")==event.get("forecast") and pre_cached.get("previous")==event.get("previous"):
        pre_cached.pop("_id",None); out["pre"]=pre_cached
    else:
        pre=await _generate(event,"pre"); await col_cache.replace_one({"_id":pre_key},{"_id":pre_key,"forecast":event.get("forecast"),"previous":event.get("previous"),**pre},upsert=True); out["pre"]=pre
    if _has_actual(event):
        post_key=_briefing_key(event,"post"); post_cached=await col_cache.find_one({"_id":post_key}) if use_cache else None
        if post_cached and post_cached.get("actual")==event.get("actual"):
            post_cached.pop("_id",None); out["post"]=post_cached
        else:
            post=await _generate(event,"post"); await col_cache.replace_one({"_id":post_key},{"_id":post_key,"actual":event.get("actual"),**post},upsert=True); out["post"]=post
    return out
async def enrich_events(events, use_cache=True):
    out=[]
    for ev in events:
        try: ai=await get_briefing(ev,use_cache=use_cache)
        except Exception as e:
            log.warning(f"enrich_events failed for {_event_label(ev)}: {e}"); ai={"event_id":ev.get("event_id"),"pre":_empty("pre",str(e)[:160]),"post":None}
        item={**ev,"ai":ai}; item.pop("_id",None); out.append(item)
    return out
