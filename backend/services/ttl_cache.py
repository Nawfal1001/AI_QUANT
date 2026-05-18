from __future__ import annotations

import time
from typing import Any, Callable, Dict, Hashable, Tuple

_CACHE: Dict[Hashable, Tuple[float, Any]] = {}


def make_key(*parts: Any) -> Tuple[Any, ...]:
    return tuple(str(p) for p in parts if p is not None)


def get(key: Hashable):
    item = _CACHE.get(key)
    if not item:
        return None
    expires_at, value = item
    if expires_at <= time.time():
        _CACHE.pop(key, None)
        return None
    return value


def set(key: Hashable, value: Any, ttl_seconds: float = 5):
    _CACHE[key] = (time.time() + float(ttl_seconds), value)
    return value


def clear(prefix: Any = None):
    if prefix is None:
        _CACHE.clear()
        return
    p = str(prefix)
    for key in list(_CACHE.keys()):
        if isinstance(key, tuple) and key and str(key[0]) == p:
            _CACHE.pop(key, None)
        elif str(key).startswith(p):
            _CACHE.pop(key, None)


async def cached(key: Hashable, ttl_seconds: float, factory: Callable[[], Any]):
    hit = get(key)
    if hit is not None:
        return hit
    value = await factory()
    return set(key, value, ttl_seconds)
