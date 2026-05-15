"""Simple in-memory rate limiting helpers for sensitive endpoints.

This protects single-process/self-hosted deployments. For multi-worker or
multi-instance production, replace with a shared Redis-backed limiter.
"""
import time
from collections import defaultdict, deque
from typing import Deque, Dict

_ATTEMPTS: Dict[str, Deque[float]] = defaultdict(deque)


def check_rate_limit(key: str, *, limit: int, window_sec: int) -> bool:
    now = time.time()
    bucket = _ATTEMPTS[key]
    while bucket and now - bucket[0] > window_sec:
        bucket.popleft()
    if len(bucket) >= limit:
        return False
    bucket.append(now)
    return True


def reset_rate_limit(key: str) -> None:
    _ATTEMPTS.pop(key, None)
