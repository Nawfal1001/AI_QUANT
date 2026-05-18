from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from typing import Any, Dict, Iterable, List, Tuple


def _oid(d: Dict[str, Any]) -> Dict[str, Any]:
    if d and d.get('_id') is not None:
        d['_id'] = str(d['_id'])
    return d


def _f(v: Any, default: float = 0.0) -> float:
    try:
        return float(v)
    except Exception:
        return default


async def live_price(ticker: str, atype: str = 'stock', timeout_sec: float = 2.5) -> Tuple[Any, Any, Any, str]:
    try:
        from services import data_freshness
        cached = data_freshness.get_price(ticker)
        if cached and cached.get('price'):
            return float(cached.get('price')), cached.get('age_sec'), cached.get('ts') or cached.get('timestamp'), 'cache'
    except Exception:
        pass
    try:
        from services.backtest_engine import fetch_history
        end_dt = datetime.utcnow(); start_dt = end_dt - timedelta(days=2)
        df = await asyncio.wait_for(
            fetch_history(ticker, atype, start_dt.strftime('%Y-%m-%d'), end_dt.strftime('%Y-%m-%d'), '1h'),
            timeout=timeout_sec,
        )
        if df is not None and len(df):
            return float(df['close'].iloc[-1]), None, end_dt.isoformat(), 'history_fallback'
    except asyncio.TimeoutError:
        return None, None, None, 'timeout'
    except Exception:
        return None, None, None, 'unavailable'
    return None, None, None, 'unavailable'


def enrich_trade(t: Dict[str, Any], live_price_value: Any, price_age_sec=None, price_ts=None, price_source='unavailable') -> Dict[str, Any]:
    entry = _f(t.get('entry_price'))
    qty = _f(t.get('quantity') or t.get('qty'))
    sl = _f(t.get('sl'))
    tp = _f(t.get('tp'))
    sig = str(t.get('signal', 'BUY')).upper()
    is_buy = 'BUY' in sig or sig == 'LONG'
    live = _f(live_price_value) if live_price_value is not None else None
    out = _oid(dict(t))
    out.update({
        'live_price': live,
        'price_age_sec': price_age_sec,
        'price_timestamp': price_ts,
        'price_source': price_source,
        'broker_synced': bool(t.get('broker_synced', False)),
        'broker_status': 'paper' if t.get('paper_mode', True) else 'app_managed_live_requested',
    })
    if live is None or entry <= 0:
        out.update({'pnl_pct': None, 'pnl_usd': None, 'distance_to_sl_pct': None, 'distance_to_tp_pct': None, 'should_close_now': False, 'close_trigger': None, 'monitor_status': 'no_live_price'})
        return out
    pnl_pct = ((live - entry) / entry * 100) if is_buy else ((entry - live) / entry * 100)
    pnl_usd = (live - entry) * qty if is_buy else (entry - live) * qty
    hit_sl = (live <= sl) if is_buy else (live >= sl)
    hit_tp = (live >= tp) if is_buy else (live <= tp)
    dist_sl = ((live - sl) / live * 100) if is_buy and live else ((sl - live) / live * 100 if live else None)
    dist_tp = ((tp - live) / live * 100) if is_buy and live else ((live - tp) / live * 100 if live else None)
    close_trigger = 'TP' if hit_tp else ('SL' if hit_sl else None)
    nearest = 'TP' if dist_tp is not None and dist_sl is not None and dist_tp < dist_sl else 'SL'
    status = 'will_close_now' if close_trigger else ('near_tp' if nearest == 'TP' and dist_tp is not None and dist_tp <= 0.5 else ('near_sl' if nearest == 'SL' and dist_sl is not None and dist_sl <= 0.5 else 'open'))
    out.update({
        'pnl_pct': round(pnl_pct, 3),
        'pnl_usd': round(pnl_usd, 4),
        'distance_to_sl_pct': round(dist_sl, 3) if dist_sl is not None else None,
        'distance_to_tp_pct': round(dist_tp, 3) if dist_tp is not None else None,
        'should_close_now': bool(close_trigger),
        'close_trigger': close_trigger,
        'next_close_condition': f'TP at {tp} / SL at {sl}',
        'monitor_status': status,
    })
    return out


async def enrich_one(t: Dict[str, Any]) -> Dict[str, Any]:
    try:
        price, age, ts, src = await asyncio.wait_for(live_price(t.get('ticker'), t.get('asset_type', 'stock')), timeout=3.0)
        return enrich_trade(t, price, age, ts, src)
    except Exception:
        return enrich_trade(t, None, None, None, 'timeout')


async def enrich_many(trades: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    items = list(trades or [])
    if not items:
        return []
    return await asyncio.gather(*(enrich_one(t) for t in items))
