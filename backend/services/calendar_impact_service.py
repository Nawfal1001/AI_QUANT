from datetime import datetime, timedelta
from typing import Any, Dict, List
from database import db
from services.economic_calendar_provider import sync_calendar
from services.economic_event_engine import process_economic_event, list_active_macro_signals, build_report_text_from_event

async def sync_save_refresh(start_date=None, end_date=None):
    return await sync_calendar(start_date=start_date, end_date=end_date)

def _has_released_values(ev: Dict[str, Any]) -> bool:
    return ev.get('actual') not in (None, '') or datetime.fromisoformat(str(ev.get('release_time')).replace('Z','+00:00').replace('+00:00','')).replace(tzinfo=None) <= datetime.utcnow()

async def analyze_event_impact(event_id: str, use_ai: bool = True, force: bool = False) -> Dict[str, Any]:
    ev = await db['economic_events'].find_one({'event_id': event_id})
    if not ev:
        return {'ok': False, 'error': 'event not found'}
    ev['_id'] = str(ev['_id'])
    if ev.get('macro_result') and not force:
        return {'ok': True, 'cached': True, 'event': ev, 'macro': ev.get('macro_result'), 'signals': await list_active_macro_signals(limit=50)}
    if not _has_released_values(ev):
        return {'ok': False, 'error': 'event not released yet', 'event': ev, 'report_text': build_report_text_from_event(ev)}
    res = await process_economic_event(ev, use_ai=use_ai)
    return {'ok': True, 'cached': False, 'event_id': event_id, **res}

async def refresh_and_analyze_due(start_date=None, end_date=None, use_ai: bool = True) -> Dict[str, Any]:
    sync = await sync_save_refresh(start_date, end_date)
    now = datetime.utcnow(); start = (now - timedelta(minutes=60)).isoformat(); end = (now + timedelta(minutes=15)).isoformat()
    docs = await db['economic_events'].find({'release_time': {'$gte': start, '$lte': end}, 'impact': {'$in': ['high','High','HIGH','medium','Medium']}}).to_list(100)
    results=[]
    for ev in docs:
        try:
            if _has_released_values(ev): results.append(await analyze_event_impact(ev.get('event_id'), use_ai=use_ai, force=False))
        except Exception as e:
            results.append({'ok': False, 'event_id': ev.get('event_id'), 'error': str(e)})
    return {'sync': sync, 'analyzed': len(results), 'results': results}
