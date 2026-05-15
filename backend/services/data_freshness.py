"""
Market data freshness gate + price cache.

- Caches prices with TTL (default 30s for live trading, 5min for backtesting context)
- Rejects orders if the last known price is older than max_age_seconds
- Backends to redis if available, else in-memory dict
"""
import time
from typing import Optional

from services.logger import child

log = child("freshness")

_cache: dict = {}    # {key: (value, expires_at_epoch)}
_freshness_threshold_sec = 60  # default 60s for any trade-relevant price


def set_price(ticker: str, price: float, ttl_sec: int = 30, source: str = "live"):
    """Cache a price with timestamp."""
    now = time.time()
    _cache[f"price:{ticker}"] = {
        "price": float(price),
        "ts": now,
        "expires": now + ttl_sec,
        "source": source,
    }


def get_price(ticker: str) -> Optional[dict]:
    """Get cached price + age. Returns None if not cached."""
    entry = _cache.get(f"price:{ticker}")
    if not entry:
        return None
    return {
        "price": entry["price"],
        "age_sec": time.time() - entry["ts"],
        "source": entry["source"],
        "expired": time.time() > entry["expires"],
    }


def is_fresh(ticker: str, max_age_sec: int = None) -> bool:
    """Is the cached price fresh enough to trade on?"""
    max_age = max_age_sec or _freshness_threshold_sec
    entry = get_price(ticker)
    if not entry:
        return False
    return entry["age_sec"] <= max_age


def check_freshness(ticker: str, max_age_sec: int = None) -> dict:
    """Returns {"fresh": bool, "reason": str}. Use before placing trades."""
    max_age = max_age_sec or _freshness_threshold_sec
    entry = get_price(ticker)
    if not entry:
        return {"fresh": False, "reason": f"No cached price for {ticker}"}
    if entry["age_sec"] > max_age:
        return {
            "fresh": False,
            "reason": f"Stale price for {ticker} ({entry['age_sec']:.1f}s old, limit {max_age}s)",
            "age_sec": entry["age_sec"],
        }
    return {"fresh": True, "age_sec": entry["age_sec"], "price": entry["price"]}


def clear_cache():
    _cache.clear()
