"""Verify the application reports REAL failures instead of faking success.

Two failure paths are exercised:

1. A database that is not reachable (connection test + execution).
2. An AI provider that is not reachable: a second backend is started on a free
   port with OLLAMA_BASE_URL pointing at a closed port, so the real error path
   runs while the developer's own Ollama server stays untouched.

Usage:

    ./.venv/Scripts/python.exe scripts/live_failure_check.py --base-url http://127.0.0.1:8001
    .venv/bin/python scripts/live_failure_check.py --base-url http://127.0.0.1:8001

Exit codes: 0 = every check passed, 1 = an application regression, 2 = the
check could not run because its own infrastructure was unavailable (BLOCKED,
reported separately from a failing assertion).
"""

from __future__ import annotations

import argparse
import os
import socket
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path

import httpx

BACKEND_DIR = Path(__file__).resolve().parents[1]
RESULTS: list[tuple[bool, str]] = []
BLOCKERS: list[str] = []


def _env(name: str, default: str) -> str:
    value = os.environ.get(name)
    return value if value not in (None, "") else default


# Nothing listens on this port; a closed port is the controlled unreachable target.
DEAD_PORT = int(_env("DEAD_PORT", "5599"))
# The runnable interpreter of the active virtualenv (CI uses .venv/bin/python).
PYTHON = sys.executable
ANALYTICS = {
    "host": _env("QM_ANALYTICS_HOST", "localhost"),
    "port": int(_env("QM_ANALYTICS_PORT", "5433")),
    "database": _env("QM_ANALYTICS_DB", "analytics"),
    "username": _env("QM_ANALYTICS_USER", "analytics_owner"),
    "password": _env("QM_ANALYTICS_PASSWORD", "analytics_password_change_me"),
}


def check(ok: bool, label: str, detail: str = "") -> bool:
    RESULTS.append((bool(ok), f"{label}{(' -- ' + detail) if detail else ''}"))
    print(f"[{'PASS' if ok else 'FAIL'}] {label}" + (f" -- {detail}" if detail else ""))
    return bool(ok)


def csrf(client: httpx.Client) -> dict[str, str]:
    token = client.cookies.get("querymind_csrf")
    return {"x-csrf-token": token} if token else {}


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def wait_ready(url: str, timeout: float = 45.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            if httpx.get(f"{url}/api/health", timeout=3).status_code == 200:
                return True
        except Exception:
            pass
        time.sleep(0.5)
    return False


def database_failure_checks(base_url: str, password: str) -> None:
    run_id = uuid.uuid4().hex[:8]
    with httpx.Client(base_url=base_url, timeout=60.0) as client:
        client.get("/api/health")
        reg = client.post(
            "/api/auth/register",
            json={
                "name": "Failure Verification",
                "email": f"fail-{run_id}@example.com",
                "password": password,
            },
            headers=csrf(client),
        )
        check(reg.status_code in (200, 201), "registered a throwaway user", f"http={reg.status_code}")

        dead_payload = {
            "name": f"Unreachable {run_id}",
            "database_type": "postgresql",
            "host": "127.0.0.1",
            "port": DEAD_PORT,
            "database_name": "analytics",
            "username": "analytics_owner",
            "password": "irrelevant",
            "ssl_mode": "disable",
        }
        test = client.post("/api/connections/test", json=dead_payload, headers=csrf(client)).json()
        check(
            test.get("success") is False and not test.get("server_version"),
            "connection test reports the real failure",
            str(test.get("message"))[:110],
        )

        created = client.post("/api/connections", json=dead_payload, headers=csrf(client))
        conn_id = created.json()["connection"]["id"] if created.status_code == 201 else None
        sql = "SELECT 1 AS ok"
        exe = client.post(
            "/api/query/execute",
            headers=csrf(client),
            json={"connection_id": conn_id, "sql": sql, "question": "sanity"},
        )
        body = exe.json() if exe.content else {}
        error = body.get("error") or {}
        check(
            exe.status_code >= 500 and error.get("code") == "db_unreachable",
            "execution against an unreachable database fails loudly",
            f"http={exe.status_code} code={error.get('code')} msg={str(error.get('message'))[:90]}",
        )
        check(
            "rows" not in body or not body.get("rows"),
            "no fabricated rows returned for a failed execution",
        )

        client.delete(f"/api/connections/{conn_id}", headers=csrf(client))


def ai_failure_checks(password: str) -> None:
    port = free_port()
    env = dict(os.environ)
    env.update(
        {
            # Port 9 (discard) is closed for HTTP: the provider cannot be reached.
            "OLLAMA_BASE_URL": f"http://127.0.0.1:{DEAD_PORT}",
            "AI_PROVIDER": "ollama",
            "APP_ENV": "development",
            "ALLOW_PRIVATE_DB_HOSTS": "true",
        }
    )
    log_path = Path(tempfile.mkdtemp(prefix="querymind-failure-")) / "ai-failure-backend.log"
    log = open(log_path, "w", encoding="utf-8")
    proc = subprocess.Popen(
        [
            PYTHON,
            "-m",
            "uvicorn",
            "app.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
        ],
        cwd=str(BACKEND_DIR),
        env=env,
        stdout=log,
        stderr=subprocess.STDOUT,
    )
    url = f"http://127.0.0.1:{port}"
    try:
        if not wait_ready(url):
            # The application under test is fine; this harness could not start it.
            BLOCKERS.append(
                f"could not start a throwaway backend on {url} to test provider outages "
                f"(see {log_path})"
            )
            print(f"[BLOCKED] could not start a throwaway backend on {url} (log: {log_path})")
            return

        with httpx.Client(base_url=url, timeout=120.0) as client:
            status = client.get("/api/health/ai").json()
            check(
                status.get("status") != "ok",
                "AI health endpoint reports the provider as unavailable",
                f"status={status.get('status')} message={str(status.get('message'))[:100]}",
            )

            run_id = uuid.uuid4().hex[:8]
            client.get("/api/health")
            client.post(
                "/api/auth/register",
                json={"name": "AI Failure", "email": f"aifail-{run_id}@example.com", "password": password},
                headers=csrf(client),
            )
            conn = client.post(
                "/api/connections",
                headers=csrf(client),
                json={
                    "name": f"AI failure conn {run_id}",
                    "database_type": "postgresql",
                    "host": ANALYTICS["host"],
                    "port": ANALYTICS["port"],
                    "database_name": ANALYTICS["database"],
                    "username": ANALYTICS["username"],
                    "password": ANALYTICS["password"],
                    "ssl_mode": "disable",
                },
            )
            conn_id = conn.json()["connection"]["id"] if conn.status_code == 201 else None
            gen = client.post(
                "/api/query/generate",
                headers=csrf(client),
                json={"connection_id": conn_id, "question": "How many orders are there?"},
            )
            body = gen.json() if gen.content else {}
            check(
                gen.status_code >= 500,
                "generation fails when the model is unreachable",
                f"http={gen.status_code} code={(body.get('error') or {}).get('code')}",
            )
            check(
                not body.get("sql"),
                "no SQL is fabricated when the model is unreachable",
                f"sql={body.get('sql')!r}",
            )
            message = str((body.get("error") or {}).get("message", ""))
            check(
                any(word in message.lower() for word in ("ollama", "model", "unavailable", "ai")),
                "error explains that the AI provider is the problem",
                message[:120],
            )
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=15)
        except subprocess.TimeoutExpired:
            proc.kill()
        log.close()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8001")
    args = parser.parse_args()
    password = "verification-passw0rd"

    print("== unreachable database ==")
    database_failure_checks(args.base_url, password)
    print("\n== unreachable AI provider ==")
    ai_failure_checks(password)

    failed = [label for ok, label in RESULTS if not ok]
    print("\n" + "=" * 72)
    print(f"FAILURE PATH CHECKS: {len(RESULTS) - len(failed)}/{len(RESULTS)} passed")
    for label in failed:
        print(" - FAILED:", label)
    for blocker in BLOCKERS:
        print(" - BLOCKED:", blocker)
    print("=" * 72)
    if failed:
        return 1
    if BLOCKERS:
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
