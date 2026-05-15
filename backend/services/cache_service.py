"""
Shared async cache service.

Uses in-memory TTL cache for hot paths and MongoDB for persistent cross-process
cache. Useful for market data, macro headlines, AI outputs, scanner universes,
and expensive broker/exchange discovery calls.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Optional

from database import db
from services.logger import child

log = child("cache_service")

_memory = {}
col_cache = db["app_cache"]


def _now() -> datetime:
    return datetime.utcnow()


def _key(ns: str, key: str) -> str:
    return f"{ns}:{key}".lower()


async def get_cache(ns: str, key: str, default: Any = None) -> Any:
    full = _key(ns, key)
    mem = _memory.get(full)
    if mem and mem["expires_at"] > _now():
        return mem["value"]
    doc = await col_cache.find_one({"_id": full})
    if not doc:
        return default
    try:
        expires = datetime.fromisoformat(doc.get("expires_at"))
        if expires <= _now():
            await col_cache.delete_one({"_id": full})
            _memory.pop(full, None)
            return default
        _memory[full] = {"value": doc.get("value"), "expires_at": expires}
        return doc.get("value")
    except Exception:
        return default


async def set_cache(ns: str, key: str, value: Any, ttl_sec: int = 300) -> Any:
    full = _key(ns, key)
    expires = _now() + timedelta(seconds=ttl_sec)
    _memory[full] = {"value": value, "expires_at": expires}
    try:
        await col_cache.replace_one(
            {"_id": full},
            {"_id": full, "namespace": ns, "key": key, "value": value, "expires_at": expires.isoformat(), "updated_at": _now().isoformat()},
            upsert=True,
        )
    except Exception as e:
        log.debug(f"cache persistence failed for {full}: {e}")
    return value


async def delete_cache(ns: str, key: str) -> None:
    full = _key(ns, key)
    _memory.pop(full, None)
    await col_cache.delete_one({"_id": full})


async def cleanup_expired_cache(limit: int = 500) -> int:
    now = _now().isoformat()
    res = await col_cache.delete_many({"expires_at": {"$lte": now}})
    return int(getattr(res, "deleted_count", 0) or 0)
