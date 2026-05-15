"""
Order idempotency.
Prevents the same trade from being placed twice due to retries or race conditions.

Strategy: hash (user_id, ticker, side, qty, minute_bucket) and reject duplicates within
a configurable window (default 60 seconds).
"""
import hashlib
import time
from typing import Optional

from services.logger import child

log = child("idempotency")

# {hash_key: expires_at_epoch}
_seen: dict = {}
DEFAULT_WINDOW_SEC = 60


def _make_key(user_id: str, ticker: str, side: str, qty: float, bucket_sec: int = 60) -> str:
    bucket = int(time.time() // bucket_sec)
    raw = f"{user_id}|{ticker}|{side}|{qty:.6f}|{bucket}"
    return hashlib.sha256(raw.encode()).hexdigest()[:24]


def _cleanup():
    """Remove expired entries to keep memory bounded."""
    now = time.time()
    expired = [k for k, v in _seen.items() if v < now]
    for k in expired:
        _seen.pop(k, None)


def check_and_record(
    user_id: str,
    ticker: str,
    side: str,
    qty: float,
    window_sec: int = DEFAULT_WINDOW_SEC,
) -> dict:
    """
    Returns {"unique": True, "key": ...} or {"unique": False, "reason": ...}.
    If unique, records the order to block duplicates within window_sec.
    """
    _cleanup()
    key = _make_key(user_id, ticker, side, qty)
    now = time.time()
    if key in _seen and _seen[key] > now:
        log.warning(f"Duplicate order blocked: {user_id} {ticker} {side} {qty}")
        return {"unique": False, "reason": f"Duplicate order in last {window_sec}s"}
    _seen[key] = now + window_sec
    return {"unique": True, "key": key}


def release(key: str):
    """Release an idempotency key (e.g. if the order failed and you want to retry)."""
    _seen.pop(key, None)
