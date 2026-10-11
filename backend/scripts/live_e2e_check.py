"""Live end-to-end verification against a RUNNING QueryMind backend.

This is not a unit test: it talks to a real HTTP server, a real PostgreSQL
analytics database and the real Ollama model, then independently re-computes
the answer in SQL to prove the API returned actual data.

Usage (backend must already be running):

    ./.venv/Scripts/python.exe scripts/live_e2e_check.py --base-url http://127.0.0.1:8001
    .venv/bin/python scripts/live_e2e_check.py --base-url http://127.0.0.1:8001

Every service endpoint is environment-overridable (QM_ANALYTICS_*,
SECOND_SCHEMA_*) with defaults that match docker-compose.yml, so the same
command works locally and in CI.

Exits non-zero if any check fails so it can gate a release.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
import uuid

import httpx
import psycopg


def _env(name: str, default: str) -> str:
    value = os.environ.get(name)
    return value if value not in (None, "") else default


ANALYTICS = {
    "host": _env("QM_ANALYTICS_HOST", "localhost"),
    "port": int(_env("QM_ANALYTICS_PORT", "5433")),
    "database": _env("QM_ANALYTICS_DB", "analytics"),
    "username": _env("QM_ANALYTICS_USER", "analytics_owner"),
    "password": _env("QM_ANALYTICS_PASSWORD", "analytics_password_change_me"),
    "ssl_mode": _env("QM_ANALYTICS_SSLMODE", "disable"),
}

QUESTION = "What are the top 5 products by total revenue? Sort highest first."

_results: list[tuple[bool, str]] = []


def check(ok: bool, label: str, detail: str = "") -> bool:
    _results.append((bool(ok), f"{label}{(' — ' + detail) if detail else ''}"))
    print(f"[{'PASS' if ok else 'FAIL'}] {label}" + (f" — {detail}" if detail else ""))
    return bool(ok)


def csrf(client: httpx.Client) -> dict[str, str]:
    token = client.cookies.get("querymind_csrf")
    return {"x-csrf-token": token} if token else {}


def independent_top_products(limit: int = 5) -> list[tuple[str, str]]:
    """Recompute the expected answer directly, independent of the application."""
    sql = """
        SELECT p.product_name,
               SUM(oi.quantity * oi.unit_price)::numeric(12,2) AS revenue
        FROM order_items oi
        JOIN products p ON p.product_id = oi.product_id
        GROUP BY p.product_name
        ORDER BY revenue DESC
        LIMIT %s
    """
    with psycopg.connect(
        host=ANALYTICS["host"],
        port=ANALYTICS["port"],
        dbname=ANALYTICS["database"],
        user=ANALYTICS["username"],
        password=ANALYTICS["password"],
        connect_timeout=10,
    ) as conn:
        rows = conn.execute(sql, (limit,)).fetchall()
    return [(str(name), str(revenue)) for name, revenue in rows]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8001")
    args = parser.parse_args()

    run_id = uuid.uuid4().hex[:8]
    email = f"e2e-{run_id}@example.com"
    password = "verification-passw0rd"

    with httpx.Client(base_url=args.base_url, timeout=180.0, follow_redirects=False) as client:
        # --- 1. health -------------------------------------------------------
        # Liveness must answer without touching the database...
        health_resp = client.get("/api/health")
        health = health_resp.json()
        check(health_resp.status_code == 200, "backend liveness")
        check(health.get("probe") == "liveness", "liveness probe declares itself")
        check("database" not in health, "liveness does not depend on the database")
        # ...while readiness is the probe that reports database reachability.
        ready_resp = client.get("/api/health/ready")
        ready = ready_resp.json()
        check(
            ready_resp.status_code == 200,
            "readiness returns HTTP 200 with the database up",
            f"http={ready_resp.status_code}",
        )
        check(
            (ready.get("database") or {}).get("connected") is True,
            "application metadata database connected",
        )

        ai = client.get("/api/health/ai").json()
        check(ai.get("status") == "ok", "AI provider reachable", f"provider={ai.get('provider')}")
        check(bool(ai.get("model")), "AI model available", f"model={ai.get('model')}")

        # --- 2. auth ---------------------------------------------------------
        reg = client.post(
            "/api/auth/register",
            json={"name": "E2E Verification", "email": email, "password": password},
            headers=csrf(client),
        )
        check(reg.status_code in (200, 201), "register", f"http={reg.status_code}")
        if reg.status_code not in (200, 201):
            print(reg.text[:400])
            return 1

        me = client.get("/api/auth/me")
        me_user = (me.json().get("user") or {}) if me.status_code == 200 else {}
        check(me.status_code == 200 and me_user.get("email") == email, "session / current user", f"http={me.status_code}")

        # --- 3. database connection -----------------------------------------
        payload = {
            "name": f"E2E analytics {run_id}",
            "database_type": "postgresql",
            "host": ANALYTICS["host"],
            "port": ANALYTICS["port"],
            "database_name": ANALYTICS["database"],
            "username": ANALYTICS["username"],
            "password": ANALYTICS["password"],
            "ssl_mode": ANALYTICS["ssl_mode"],
        }
        test = client.post("/api/connections/test", json=payload, headers=csrf(client))
        test_body = test.json()
        check(
            test_body.get("success") is True,
            "connection test against real PostgreSQL",
            f"server_version={test_body.get('server_version')} latency_ms={test_body.get('latency_ms')}",
        )

        created = client.post("/api/connections", json=payload, headers=csrf(client))
        check(created.status_code == 201, "save connection", f"http={created.status_code}")
        conn_id = ((created.json().get("connection") or {}).get("id")) if created.status_code == 201 else None
        if not conn_id:
            print(created.text[:400])
            return 1

        public = created.json()["connection"]
        check("password" not in public and public.get("has_password") is True, "stored password never returned")
        check("encrypted_credentials" not in public, "encrypted blob never returned")

        listing = client.get("/api/connections").json()
        check(
            all("password" not in c for c in listing.get("items", [])),
            "connection list exposes no secrets",
        )

        # --- 4. schema discovery --------------------------------------------
        schema_resp = client.get(f"/api/connections/{conn_id}/schema")
        schema = schema_resp.json()
        tables = {t.get("name") for t in (schema.get("tables") or [])}
        check(
            {"orders", "order_items", "products", "customers"} <= tables,
            "schema discovered from the live database",
            f"tables={sorted(tables)}",
        )
        rels = schema.get("relationships") or []
        check(len(rels) > 0, "foreign-key relationships discovered", f"count={len(rels)}")
        columns = [c for t in (schema.get("tables") or []) for c in (t.get("columns") or [])]
        check(any(c.get("pk") for c in columns), "primary keys discovered")
        check(all(c.get("type") for c in columns), "column data types discovered")

        # --- 5. real LLM generation -----------------------------------------
        started = time.perf_counter()
        gen = client.post(
            "/api/query/generate",
            json={"connection_id": conn_id, "question": QUESTION},
            headers=csrf(client),
        )
        gen_body = gen.json() if gen.status_code == 200 else {}
        gen_ms = int((time.perf_counter() - started) * 1000)
        generated_sql = gen_body.get("sql") or ""
        check(bool(generated_sql), "LLM generated SQL", f"{gen_ms} ms")
        print("       SQL:", " ".join(generated_sql.split())[:400])
        validation = gen_body.get("validation") or {}
        check(validation.get("valid") is True, "generated SQL passed independent validation")
        check(bool(gen_body.get("explanation")), "plain-English SQL explanation returned")

        # --- 6. validate endpoint -------------------------------------------
        val = client.post(
            "/api/query/validate",
            json={"connection_id": conn_id, "sql": generated_sql},
            headers=csrf(client),
        )
        check((val.json().get("validation") or {}).get("valid") is True, "POST /api/query/validate")

        # --- 7. execute + compare against independent SQL -------------------
        exe = client.post(
            "/api/query/execute",
            json={"connection_id": conn_id, "sql": generated_sql, "question": QUESTION},
            headers=csrf(client),
        )
        exe_body = exe.json() if exe.status_code == 200 else {}
        check(exe.status_code == 200, "execute approved read-only query", f"http={exe.status_code}")
        if exe.status_code != 200:
            print(exe.text[:500])
            return 1

        columns = [c.get("name") for c in (exe_body.get("columns") or [])]
        rows = exe_body.get("rows") or []
        meta = exe_body.get("metadata") or {}
        check(rows and len(rows) == meta.get("row_count"), "actual rows returned", f"row_count={meta.get('row_count')} time_ms={meta.get('execution_time_ms')}")
        check(bool(meta.get("execution_time_ms", 0)), "execution time measured by the server")
        check(bool((exe_body.get("chart") or {}).get("type")), "chart recommendation", f"type={(exe_body.get('chart') or {}).get('type')}")
        check(bool(exe_body.get("history_id")), "execution persisted to query history")

        expected = independent_top_products()
        print("       independent SQL result:", expected)
        name_idx = next((i for i, c in enumerate(columns) if c and "product" in c.lower()), None)
        rev_idx = next(
            (i for i, c in enumerate(columns) if c and ("revenue" in c.lower() or "total" in c.lower())),
            None,
        )
        if name_idx is None or rev_idx is None:
            check(False, "result columns identify product and revenue", f"columns={columns}")
        else:
            api_pairs = [(str(r[name_idx]), f"{float(r[rev_idx]):.2f}") for r in rows[:5]]
            print("       API result:            ", api_pairs)
            check(
                {n.lower() for n, _ in api_pairs} == {n.lower() for n, _ in expected},
                "top products match an independently executed query",
            )
            check(
                {r for _, r in api_pairs} == {r for _, r in expected},
                "revenue totals match an independently executed query",
            )

        # --- 8. unsafe SQL must be rejected ---------------------------------
        for bad in ("DROP TABLE customers", "SELECT 1; DELETE FROM orders;", "UPDATE products SET unit_price = 0"):
            v = client.post(
                "/api/query/validate",
                json={"connection_id": conn_id, "sql": bad},
                headers=csrf(client),
            )
            check(
                (v.json().get("validation") or {}).get("valid") is False,
                f"unsafe SQL rejected: {bad!r}",
                "; ".join((v.json().get("validation") or {}).get("errors") or [])[:140],
            )
            blocked = client.post(
                "/api/query/execute",
                json={"connection_id": conn_id, "sql": bad},
                headers=csrf(client),
            )
            check(blocked.status_code == 400, f"unsafe SQL not executed: {bad!r}", f"http={blocked.status_code}")

        # --- 9. history, saved queries, analytics ---------------------------
        hist = client.get("/api/history", params={"connection_id": conn_id}).json()
        check(bool(hist.get("items")), "history lists the executions", f"count={hist.get('total', len(hist.get('items') or []))}")

        saved = client.post(
            "/api/saved-queries",
            json={
                "connection_id": conn_id,
                "title": "Top products by revenue",
                "description": "E2E verification",
                "natural_language_question": QUESTION,
                "sql_query": generated_sql,
                "tags": ["e2e"],
                "is_favorite": True,
            },
            headers=csrf(client),
        )
        check(saved.status_code in (200, 201), "save query", f"http={saved.status_code}")
        saved_id = ((saved.json().get("item") or saved.json().get("saved_query") or {}).get("id")) if saved.status_code in (200, 201) else None

        overview = client.get("/api/analytics/overview").json()
        stats = overview.get("stats") or {}
        check(
            stats.get("total_queries", 0) >= 1 and stats.get("connections", 0) >= 1,
            "dashboard analytics computed from real rows",
            f"connections={stats.get('connections')} queries={stats.get('total_queries')} "
            f"successful={stats.get('successful_queries')} avg_ms={stats.get('avg_execution_time_ms')}",
        )
        check(bool(overview.get("recent_activity")), "recent activity from query history")

        # --- 10. conversation follow-up -------------------------------------
        conv = client.post(
            "/api/conversations",
            json={"connection_id": conn_id, "title": "E2E follow-up"},
            headers=csrf(client),
        )
        conv_id = ((conv.json().get("conversation") or conv.json().get("item") or {}).get("id")) if conv.status_code in (200, 201) else None
        check(bool(conv_id), "create conversation", f"http={conv.status_code}")
        if conv_id:
            msg = client.post(
                f"/api/conversations/{conv_id}/messages",
                json={"question": "Only include orders from 2025.", "connection_id": conn_id},
                headers=csrf(client),
            )
            msg_body = msg.json() if msg.status_code == 200 else {}
            follow_up_sql = msg_body.get("sql") or msg_body.get("generated_sql") or ""
            check(
                bool(follow_up_sql) and follow_up_sql.strip() != generated_sql.strip(),
                "contextual follow-up produced a new query",
                f"http={msg.status_code}",
            )

        # --- 11. cross-tenant isolation -------------------------------------
        with httpx.Client(base_url=args.base_url, timeout=60.0) as other:
            other.get("/api/health")
            other_reg = other.post(
                "/api/auth/register",
                json={"name": "E2E Other", "email": f"e2e-other-{run_id}@example.com", "password": password},
                headers=csrf(other),
            )
            check(other_reg.status_code in (200, 201), "second user registered", f"http={other_reg.status_code}")
            stolen = other.get(f"/api/connections/{conn_id}")
            check(stolen.status_code in (403, 404), "another user cannot read this connection", f"http={stolen.status_code}")
            stolen_schema = other.get(f"/api/connections/{conn_id}/schema")
            check(
                stolen_schema.status_code in (403, 404),
                "another user cannot read this connection's schema",
                f"http={stolen_schema.status_code}",
            )

        # --- 12. a different database with a completely different schema -----
        second = {
            "name": f"E2E second schema {run_id}",
            "database_type": "postgresql",
            "host": os.environ.get("SECOND_SCHEMA_HOST", "localhost"),
            "port": int(os.environ.get("SECOND_SCHEMA_PORT", "5434")),
            "database_name": os.environ.get("SECOND_SCHEMA_DB", "querymind"),
            "username": os.environ.get("SECOND_SCHEMA_USER", "app_user"),
            "password": os.environ.get("SECOND_SCHEMA_PASSWORD", "app_password_change_me"),
            "ssl_mode": "disable",
        }
        second_resp = client.post("/api/connections", json=second, headers=csrf(client))
        second_id = (
            (second_resp.json().get("connection") or {}).get("id")
            if second_resp.status_code == 201
            else None
        )
        if second_id:
            tables_2 = {
                t.get("name")
                for t in (client.get(f"/api/connections/{second_id}/schema").json().get("tables") or [])
            }
            check(
                "users" in tables_2 and "products" not in tables_2,
                "second database has a different schema",
                f"tables={sorted(tables_2)[:6]}",
            )
            question_2 = "How many user accounts are registered?"
            with psycopg.connect(
                host=second["host"],
                port=second["port"],
                dbname=second["database_name"],
                user=second["username"],
                password=second["password"],
                connect_timeout=10,
            ) as probe:
                before = int(probe.execute("SELECT COUNT(*) FROM users").fetchone()[0])
            gen_2 = client.post(
                "/api/query/generate",
                json={"connection_id": second_id, "question": question_2},
                headers=csrf(client),
            ).json()
            sql_2 = gen_2.get("sql") or ""
            print("       SQL (second schema):", " ".join(sql_2.split())[:300])
            check(
                "users" in sql_2.lower() and "orders" not in sql_2.lower(),
                "generation adapts to the second schema",
            )
            exe_2 = client.post(
                "/api/query/execute",
                json={"connection_id": second_id, "sql": sql_2, "question": question_2},
                headers=csrf(client),
            )
            body_2 = exe_2.json() if exe_2.status_code == 200 else {}
            value = (body_2.get("rows") or [[None]])[0][0]
            check(
                exe_2.status_code == 200 and isinstance(value, int) and value >= 1,
                "second-schema query returned a real count",
                f"rows={body_2.get('rows')}",
            )
            with psycopg.connect(
                host=second["host"],
                port=second["port"],
                dbname=second["database_name"],
                user=second["username"],
                password=second["password"],
                connect_timeout=10,
            ) as conn:
                after = int(conn.execute("SELECT COUNT(*) FROM users").fetchone()[0])
            # The expected value is computed independently and never hardcoded;
            # the range guards against another writer inserting rows mid-check.
            check(
                before <= int(value) <= after and (before != after or int(value) == before),
                "second-schema count matches an independent count",
                f"api={value} direct_before={before} direct_after={after}",
            )
            client.delete(f"/api/connections/{second_id}", headers=csrf(client))

        # --- 13. cleanup -----------------------------------------------------
        if saved_id:
            client.delete(f"/api/saved-queries/{saved_id}", headers=csrf(client))
        removed = client.delete(f"/api/connections/{conn_id}", headers=csrf(client))
        check(removed.status_code in (200, 204), "delete connection", f"http={removed.status_code}")

    failed = [label for ok, label in _results if not ok]
    print("\n" + "=" * 72)
    print(f"LIVE E2E: {len(_results) - len(failed)}/{len(_results)} checks passed")
    if failed:
        print("FAILED CHECKS:")
        for label in failed:
            print(" -", label)
    print("=" * 72)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
