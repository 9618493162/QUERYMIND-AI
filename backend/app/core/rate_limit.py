"""Minimal in-process fixed-window rate limiter (per key, per minute).

Behavior
--------
- Fixed window of one minute per key.
- Keys are built as ``bucket:client_key``. The client key is the direct peer
  address, unless that peer is a configured trusted proxy
  (``TRUSTED_PROXY_IPS``), in which case ``X-Forwarded-For`` is walked from
  right to left and the first untrusted address is used. The header is ignored
  entirely when no trusted proxy is configured.
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

import ipaddress
import threading
import time
from collections import defaultdict
from functools import lru_cache

from fastapi import Request

from app.core.config import settings
from app.core.errors import ApiError

_lock = threading.Lock()
_hits: dict[str, list[float]] = defaultdict(list)
_WINDOW_SECONDS = 60.0


@lru_cache(maxsize=8)
def _trusted_networks(spec: str) -> tuple[ipaddress._BaseNetwork, ...]:
    """Parse the configured trusted proxies (plain IPs and CIDRs)."""
    networks: list[ipaddress._BaseNetwork] = []
    for entry in (p.strip() for p in spec.split(",")):
        if not entry:
            continue
        try:
            networks.append(ipaddress.ip_network(entry, strict=False))
        except ValueError:
            continue
    return tuple(networks)


def _is_trusted(ip: ipaddress._BaseAddress, networks: tuple[ipaddress._BaseNetwork, ...]) -> bool:
    return any(ip in net for net in networks)


def client_key(request: Request) -> str:
    """Identify the client for rate limiting.

    ``X-Forwarded-For`` is client-controlled, so it is only believed when the
    immediate peer is a configured trusted proxy. The chain is then walked from
    right to left (the direction our own proxy appends to), skipping trusted
    hops, and the first untrusted address wins. A spoofed left-most entry is
    therefore ignored, and with no trusted proxy configured the header is
    ignored entirely.
    """
    peer = request.client.host if request.client else None
    if not peer:
        return "unknown"

    networks = _trusted_networks(settings.trusted_proxy_ips)
    try:
        peer_ip: ipaddress._BaseAddress | None = ipaddress.ip_address(peer)
    except ValueError:
        peer_ip = None

    if not networks or peer_ip is None or not _is_trusted(peer_ip, networks):
        return peer

    forwarded = request.headers.get("x-forwarded-for") or ""
    for candidate in reversed([p.strip() for p in forwarded.split(",") if p.strip()]):
        try:
            candidate_ip = ipaddress.ip_address(candidate)
        except ValueError:
            continue  # unparseable hop: skip rather than trust it
        if not _is_trusted(candidate_ip, networks):
            return candidate
    return peer


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
