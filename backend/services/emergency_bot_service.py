from datetime import datetime
from typing import Dict, Any, List, Optional
from database import db
from services.economic_event_engine import list_active_macro_signals

col_cfg = db['emergency_bot_config']
col_actions = db['emergency_bot_actions']

DEFAULT_CFG = {
    'enabled': False,
    'paper_only': True,
    'min_confidence': 70,
    'require_price_confirmation': True,
    'max_signals_per_run': 10,
    'allowed_asset_types': ['forex', 'crypto', 'stock', 'gold', 'oil'],
    'status': 'stopped',
}

def _now(): return datetime.utcnow().isoformat()

async def get_config() -> Dict[str, Any]:
    doc = await col_cfg.find_one({'_id': 'default'})
    if not doc:
        doc = {'_id': 'default', **DEFAULT_CFG, 'updated_at': _now()}
        await col_cfg.replace_one({'_id': 'default'}, doc, upsert=True)
    doc['_id'] = str(doc['_id'])
    return doc

async def update_config(patch: Dict[str, Any]) -> Dict[str, Any]:
    allowed = set(DEFAULT_CFG.keys())
    clean = {k: v for k, v in patch.items() if k in allowed}
    clean['updated_at'] = _now()
    await col_cfg.update_one({'_id': 'default'}, {'$set': clean}, upsert=True)
    return await get_config()

async def evaluate_macro_signals(asset_type: Optional[str] = None) -> Dict[str, Any]:
    cfg = await get_config()
    signals = await list_active_macro_signals(asset_type=asset_type, limit=int(cfg.get('max_signals_per_run', 10)))
    actions = []
    for s in signals:
        if s.get('asset_type') not in cfg.get('allowed_asset_types', []):
            continue
        if float(s.get('confidence', 0) or 0) < float(cfg.get('min_confidence', 70)):
            continue
        action = {
            'ticker': s.get('ticker'), 'asset_type': s.get('asset_type'), 'signal': s.get('signal'),
            'confidence': s.get('confidence'), 'event_id': s.get('event_id'), 'event_name': s.get('event_name'),
            'reason': s.get('reason'), 'status': 'candidate' if not cfg.get('enabled') else 'paper_ready',
            'paper_only': bool(cfg.get('paper_only', True)), 'created_at': _now(), 'source': 'macro_emergency_signal',
        }
        await col_actions.insert_one(action)
        action.pop('_id', None)
        actions.append(action)
    return {'config': cfg, 'signals_seen': len(signals), 'actions': actions, 'enabled': cfg.get('enabled')}

async def list_actions(limit: int = 50) -> List[Dict[str, Any]]:
    docs = await col_actions.find({}).sort('created_at', -1).limit(limit).to_list(limit)
    for d in docs: d['_id'] = str(d['_id'])
    return docs
