from __future__ import annotations

import os
import time
from typing import Any, Callable, Dict, Tuple

from services.logger import child as _child_log

_log = _child_log("ai_quota_guard")

_CACHE: Dict[str, Tuple[float, Any]] = {}
_CALL_DAYS: Dict[str, int] = {}
_COOLDOWN_UNTIL = 0.0


def _now() -> float:
    return time.time()


def _today() -> str:
    return time.strftime("%Y-%m-%d", time.gmtime())


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, default))
    except Exception:
        return default


def _env_bool(name: str, default: bool) -> bool:
    raw = str(os.getenv(name, str(default))).lower().strip()
    return raw in ("1", "true", "yes", "on")


def cache_ttl_seconds(kind: str = "signal") -> int:
    if kind == "research":
        return _env_int("AI_RESEARCH_CACHE_TTL_SECONDS", 60 * 60 * 12)
    return _env_int("AI_SIGNAL_CACHE_TTL_SECONDS", 60 * 60 * 4)


def make_key(kind: str, *parts: Any) -> str:
    clean = ":".join(str(p).strip().upper() for p in parts if p is not None)
    return f"ai:{kind}:{clean}"


def daily_limit() -> int:
    return _env_int("AI_MAX_CALLS_PER_DAY", 15)


def calls_today() -> int:
    return _CALL_DAYS.get(_today(), 0)


def can_call_ai() -> Tuple[bool, str]:
    if not _env_bool("AI_CONFIRMATION_ENABLED", True):
        return False, "AI disabled by AI_CONFIRMATION_ENABLED=false"
    if _now() < _COOLDOWN_UNTIL:
        return False, f"AI quota cooldown active for {int(_COOLDOWN_UNTIL - _now())}s"
    if calls_today() >= daily_limit():
        return False, f"AI daily call budget reached ({calls_today()}/{daily_limit()})"
    return True, "ok"


def mark_call() -> None:
    day = _today()
    _CALL_DAYS[day] = _CALL_DAYS.get(day, 0) + 1
    for d in list(_CALL_DAYS.keys()):
        if d != day:
            _CALL_DAYS.pop(d, None)


def trigger_cooldown(reason: str = "quota") -> None:
    global _COOLDOWN_UNTIL
    minutes = _env_int("AI_QUOTA_COOLDOWN_MINUTES", 720)
    _COOLDOWN_UNTIL = max(_COOLDOWN_UNTIL, _now() + minutes * 60)
    _log.warning(f"AI cooldown enabled for {minutes}m: {reason}")


def is_quota_error(exc: Exception) -> bool:
    text = str(exc).lower()
    return "429" in text or "quota" in text or "rate-limit" in text or "rate limit" in text


def get_cached(key: str):
    item = _CACHE.get(key)
    if not item:
        return None
    expires, value = item
    if expires <= _now():
        _CACHE.pop(key, None)
        return None
    return value


def set_cached(key: str, value: Any, ttl: int) -> Any:
    _CACHE[key] = (_now() + ttl, value)
    return value


def guarded_fallback(base: Dict[str, Any], reason: str, cached: Any = None) -> Dict[str, Any]:
    if cached:
        data = dict(cached)
        data["ai_cached"] = True
        data["ai_guard_reason"] = reason
        return data
    data = dict(base)
    data["ai_cached"] = False
    data["ai_guard_reason"] = reason
    return data


def status() -> Dict[str, Any]:
    return {
        "enabled": _env_bool("AI_CONFIRMATION_ENABLED", True),
        "calls_today": calls_today(),
        "daily_limit": daily_limit(),
        "cooldown_active": _now() < _COOLDOWN_UNTIL,
        "cooldown_remaining_sec": max(0, int(_COOLDOWN_UNTIL - _now())),
        "signal_cache_entries": len(_CACHE),
    }
