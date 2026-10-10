"""Minimal in-process fixed-window rate limiter (per key, per minute).

Kept dependency-free and process-local; suitable for a single-instance
deployment. For multi-instance deployments swap for a shared store.
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict

from fastapi import Request

from app.core.errors import ApiError

_lock = threading.Lock()
_hits: dict[str, list[float]] = defaultdict(list)
_WINDOW_SECONDS = 60.0


def client_key(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def check_rate_limit(bucket: str, key: str, limit_per_minute: int) -> None:
    if limit_per_minute <= 0:
        return
    now = time.monotonic()
    k = f"{bucket}:{key}"
    with _lock:
        hits = _hits[k]
        cutoff = now - _WINDOW_SECONDS
        hits = [t for t in hits if t > cutoff]
        if len(hits) >= limit_per_minute:
            _hits[k] = hits
            raise ApiError(
                429,
                "rate_limited",
                "Too many requests. Please wait a moment and try again.",
            )
        hits.append(now)
        _hits[k] = hits


def reset() -> None:
    with _lock:
        _hits.clear()


def rate_limit(request: Request, bucket: str, limit_per_minute: int) -> None:
    check_rate_limit(bucket, client_key(request), limit_per_minute)
