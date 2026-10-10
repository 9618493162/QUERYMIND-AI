"""Classification of low-level database connection errors.

Both the connection-test endpoint and the schema/execution paths need to tell
"the server is not reachable" apart from "the credentials or permissions are
wrong", so the user gets an accurate message instead of a generic failure.
"""

from __future__ import annotations

_UNREACHABLE_MARKERS = (
    "could not connect",
    "connection refused",
    "connection failed",
    "could not translate host name",
    "name or service not known",
    "no route to host",
    "network is unreachable",
    "timeout",
    "timed out",
    "server closed the connection",
    "terminating connection",
    "10061",
    "10060",
)

_AUTH_MARKERS = (
    "password authentication failed",
    "authentication failed",
    "no password supplied",
    "invalid password",
)

_FORBIDDEN_MARKERS = (
    "permission denied",
    "must be owner",
    "insufficient privilege",
)

_MISSING_DB_MARKERS = ("does not exist",)


def is_unreachable(exc: BaseException) -> bool:
    message = str(exc).lower()
    if any(marker in message for marker in _AUTH_MARKERS):
        return False
    return any(marker in message for marker in _UNREACHABLE_MARKERS)


def friendly_connection_error(exc: BaseException, host: str, port: int) -> str:
    message = str(exc)
    lowered = message.lower()

    if any(marker in lowered for marker in _AUTH_MARKERS):
        return "Authentication failed: check the username and password."
    if any(marker in lowered for marker in _FORBIDDEN_MARKERS):
        return "The database role is not permitted to perform this operation."
    if "no pg_hba.conf entry" in lowered:
        return "The server's host-based authentication policy rejected this client."
    if "connection refused" in lowered or "10061" in lowered:
        return f"Connection refused at {host}:{port}. Is the server running and reachable?"
    if "could not translate host name" in lowered or "name or service not known" in lowered:
        return f"Could not resolve the host name {host}."
    if "does not exist" in lowered and "database" in lowered:
        return "The database name does not exist on the server."
    if any(marker in lowered for marker in ("timeout", "timed out", "10060")):
        return f"Connection to {host}:{port} timed out."
    if is_unreachable(exc):
        return f"Could not connect to the database at {host}:{port}."
    return f"Connection failed: {message.strip().splitlines()[0][:200]}"
