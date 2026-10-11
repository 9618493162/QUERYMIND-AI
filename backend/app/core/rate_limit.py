"""Minimal in-process fixed-window rate limiter (per key, per minute).

Behavior
--------
- Fixed window of one minute per key.
- Keys are built as ``bucket:client_key`` where the client key is taken from
  ``X-Forwarded-For`` (first entry) if present, otherwise the direct client IP.
- When the limit is exceeded the request is rejected immediately with a 429.
- The limiter is process-local: each uvicorn worker/instance keeps its own
  hit counters.

Limitations
-----------
- Because counters are in-memory and per-process, they do NOT coordinate across
  multiple application instances or multiple workers. In a multi-instance or
  multi-worker deployment the effective limit is roughly
  ``limit_per_minute * number_of_workers_or_instances`` for the same client.
- The in-process store is unbounded in the number of distinct keys seen over
  time. Under very high cardinality (many distinct client keys) memory can grow
  slowly; the current codebase relies on restarts and low key diversity for now.

When this is enough
-------------------
- Single-instance or single-worker deployments.
- Local development and the current CI approach.
- Defense-in-depth throttling where a shared store is not required.

When to replace it
------------------
- If you run more than one application instance or worker and want a real
  per-client limit, move the limiter to a shared store (for example Redis) or
  push rate limiting to the edge/proxy layer (for example a CDN or load
  balancer) before requests reach the app.
- If you want cross-process correctness today, do not rely on this module alone.

No new dependency is introduced by this module; if/when a shared store is
needed, add it explicitly and migrate callers behind the existing
``rate_limit(...)`` interface.
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
