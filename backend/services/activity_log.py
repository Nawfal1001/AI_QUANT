"""Central activity log helpers for debugging bots, signals, backtests and trading."""
from datetime import datetime
from database import db

col = db["activity_logs"]

async def log_event(scope: str, message: str, level: str = "info", user_id: str = None, entity_id: str = None, data: dict = None):
    doc = {"ts": datetime.utcnow().isoformat(), "scope": scope, "level": level, "message": message, "user_id": user_id, "entity_id": entity_id, "data": data or {}}
    try:
        await col.insert_one(doc)
    except Exception:
        pass
    return doc

async def get_logs(scope: str = None, user_id: str = None, entity_id: str = None, limit: int = 200):
    q = {}
    if scope: q["scope"] = scope
    if user_id: q["user_id"] = user_id
    if entity_id: q["entity_id"] = entity_id
    limit = max(1, min(int(limit or 200), 1000))
    docs = await col.find(q).sort("ts", -1).limit(limit).to_list(limit)
    for d in docs:
        d["_id"] = str(d["_id"])
    return list(reversed(docs))
