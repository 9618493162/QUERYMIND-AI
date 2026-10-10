"""Network destination policy for user-supplied database hosts (SSRF defense).

Blocks cloud metadata endpoints, and (unless explicitly allowed) loopback and
private-network destinations. An optional host allowlist can pin allowed
destinations in production.
"""

from __future__ import annotations

import ipaddress
import socket

from app.core.config import settings
from app.core.errors import ApiError

# Cloud metadata / link-local ranges that must never be reachable.
_BLOCKED_NETWORKS = [
    ipaddress.ip_network("169.254.0.0/16"),   # link-local incl. AWS/GCP/Azure metadata
    ipaddress.ip_network("100.100.100.200/32"),
    ipaddress.ip_network("fd00:ec2::254/128"),
]

_LOOPBACK = ipaddress.ip_network("127.0.0.0/8")
_V6_LOOPBACK = ipaddress.ip_network("::1/128")
_PRIVATE = ipaddress.ip_network("10.0.0.0/8")
_PRIVATE_172 = ipaddress.ip_network("172.16.0.0/12")
_PRIVATE_192 = ipaddress.ip_network("192.168.0.0/16")
_V6_ULA = ipaddress.ip_network("fc00::/7")


def resolve_host(host: str) -> list[ipaddress._BaseAddress]:
    try:
        infos = socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        raise ApiError(400, "dns_failed", f"Could not resolve database host '{host}'.") from exc
    addresses: list[ipaddress._BaseAddress] = []
    for info in infos:
        addr = info[4][0]
        try:
            addresses.append(ipaddress.ip_address(addr))
        except ValueError:
            continue
    if not addresses:
        raise ApiError(400, "dns_failed", f"Could not resolve database host '{host}'.")
    return addresses


def _is_private_or_loopback(ip: ipaddress._BaseAddress) -> bool:
    if ip in _LOOPBACK or ip in _V6_LOOPBACK:
        return True
    for net in (_PRIVATE, _PRIVATE_172, _PRIVATE_192, _V6_ULA):
        if ip in net:
            return True
    return ip.is_private or ip.is_link_local or ip.is_reserved


def assert_destination_allowed(host: str) -> None:
    """Raise ApiError(400) when the host must not be contacted."""
    allowlist = settings.allowlist_hosts
    if allowlist and host not in allowlist:
        raise ApiError(
            400,
            "destination_not_allowed",
            "This database host is not on the allowed destinations list.",
        )

    addresses = resolve_host(host)
    for ip in addresses:
        for net in _BLOCKED_NETWORKS:
            if ip in net:
                raise ApiError(
                    400,
                    "destination_not_allowed",
                    "This database host resolves to a prohibited network destination.",
                )

        if _is_private_or_loopback(ip) and not settings.allow_private_db_hosts:
            raise ApiError(
                400,
                "destination_not_allowed",
                "Private or loopback database hosts are not permitted in this deployment "
                "(set ALLOW_PRIVATE_DB_HOSTS=true for local development).",
            )
