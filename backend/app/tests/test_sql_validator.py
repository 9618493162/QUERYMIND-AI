"""SQL security validation tests — the core defense against unsafe model output."""

from __future__ import annotations

import pytest

from app.services.sql_validator import validate_sql

ALLOWED = {
    "public": {"orders", "customers", "products", "order_items", "regions", "monthly_sales"},
    "analytics": {"sales"},
}
SCHEMAS = {"public", "analytics"}


def check(sql: str, allowed=None, schemas=None):
    return validate_sql(
        sql,
        allowed_tables=allowed if allowed is not None else ALLOWED,
        allowed_schemas=schemas if schemas is not None else SCHEMAS,
    )


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT 1",
        "SELECT * FROM orders LIMIT 10",
        "SELECT c.full_name, SUM(o.amount) FROM customers c JOIN orders o ON o.customer_id = c.customer_id GROUP BY 1 ORDER BY 2 DESC LIMIT 5",
        "WITH recent AS (SELECT * FROM orders WHERE order_date >= '2025-01-01') SELECT count(*) FROM recent",
        "SELECT region, revenue FROM analytics.sales UNION ALL SELECT region, 0 FROM analytics.sales",
        "SELECT (SELECT max(total) FROM orders) AS max_total",
        "SELECT CASE WHEN qty > 10 THEN 'big' ELSE 'small' END FROM order_items",
        'SELECT "Order_ID" FROM orders',
        "select o.status, count(*) from orders o where o.status is not null group by o.status",
        "SELECT date_trunc('month', order_date) m, count(*) FROM orders GROUP BY 1 ORDER BY 1",
        "SELECT * FROM orders o LEFT JOIN customers c ON c.customer_id = o.customer_id WHERE c.region_id IS NULL",
        "SELECT percentile_cont(0.5) WITHIN GROUP (ORDER BY total) FROM orders",
        "SELECT jsonb_build_object('a', 1) FROM orders LIMIT 1",
        "SELECT * FROM orders OFFSET 10 FETCH FIRST 5 ROWS ONLY",
    ],
)
def test_safe_queries_allowed(sql):
    result = check(sql)
    assert result.valid, result.errors


@pytest.mark.parametrize(
    "sql",
    [
        "INSERT INTO orders (customer_id) VALUES (1)",
        "UPDATE orders SET status = 'x'",
        "DELETE FROM orders",
        "DROP TABLE orders",
        "ALTER TABLE orders ADD COLUMN x int",
        "CREATE TABLE evil (id int)",
        "TRUNCATE orders",
        "GRANT SELECT ON orders TO public",
        "REVOKE SELECT ON orders FROM public",
        "SELECT * FROM orders; DROP TABLE orders",
        "SELECT 1; SELECT 2",
        "COPY orders TO STDOUT",
        "CALL pg_terminate_backend(1)",
        "SELECT * INTO new_table FROM orders",
        "WITH x AS (DELETE FROM orders RETURNING *) SELECT * FROM x",
        "WITH x AS (UPDATE orders SET status='x' RETURNING *) SELECT * FROM x",
        "SELECT pg_read_file('/etc/passwd')",
        "SELECT lo_import('/etc/passwd')",
        "SELECT dblink('host=x', 'select 1')",
        "SELECT nextval('orders_seq')",
        "SELECT setval('orders_seq', 1)",
        "MERGE INTO orders USING x ON true WHEN MATCHED THEN DELETE;",
        "SET role postgres",
        "SHOW password",
        "VACUUM",
        "REINDEX TABLE orders",
        "EXPLAIN ANALYZE DELETE FROM orders",
        "SELECT * FROM secret_table",
        "SELECT * FROM pg_catalog.pg_shadow",
        "SELECT * FROM information_schema.tables",
        "SELECT * FROM analytics.hidden_table",
        "SELECT * FROM other_schema.orders",
    ],
)
def test_unsafe_or_unauthorized_queries_rejected(sql):
    result = check(sql)
    assert not result.valid, f"expected rejection for: {sql} -> {result.errors}"


def test_comment_obfuscation_still_rejected():
    sql = "SELECT 1 /* sneaky */; /* comment */ DROP TABLE orders"
    assert not check(sql).valid


def test_trailing_semicolon_single_statement_ok():
    assert check("SELECT * FROM orders;").valid


def test_multiple_statements_with_newlines_rejected():
    assert not check("SELECT * FROM orders\n;\nDELETE FROM orders").valid


def test_case_insensitive_ddl_rejected():
    assert not check("dRoP tAbLe orders").valid


def test_quoted_identifier_cannot_smuggle_table():
    assert not check('SELECT * FROM "evil_table"').valid


def test_cte_names_allowed_but_unknown_tables_rejected():
    ok = check("WITH tmp AS (SELECT * FROM orders) SELECT * FROM tmp")
    assert ok.valid
    bad = check("WITH tmp AS (SELECT * FROM not_allowed) SELECT * FROM tmp")
    assert not bad.valid


def test_unqualified_table_allowed_only_if_known():
    assert check("SELECT * FROM orders").valid
    assert not check("SELECT * FROM unknown_thing").valid


def test_empty_and_garbage_rejected():
    assert not check("").valid
    assert not check("   ").valid
    assert not check("not a sql statement at all !!!").valid


def test_error_messages_are_reported():
    result = check("DELETE FROM orders")
    assert result.errors
    assert "not allowed" in " ".join(result.errors).lower() or "select" in " ".join(result.errors).lower()


def test_too_long_rejected():
    sql = "SELECT " + ", ".join(str(i) for i in range(5000))
    assert not check(sql).valid


@pytest.mark.parametrize(
    "sql",
    [
        # Smuggling an unauthorized table inside nesting / set operations.
        "SELECT * FROM (SELECT * FROM secret_table) t",
        "SELECT * FROM orders UNION ALL SELECT * FROM secret_table",
        "SELECT * FROM orders ORDER BY (SELECT * FROM secret_table)",
        "SELECT * FROM analytics.sales s JOIN secret_table t ON true",
        "WITH d AS (SELECT 1) INSERT INTO orders SELECT * FROM d",
        # Keywords split by comments, or hidden inside quoted identifiers.
        "DR/**/OP TABLE orders",
        'SELECT * FROM "orders; DROP TABLE orders"',
        'SELECT * FROM public."orders; DROP TABLE orders"',
        # Malformed statements must never be executed.
        "SELECT * FROM orders WHERE EXISTS (DELETE FROM orders)",
        "SELECT * FROM orders WHERE id = 1 /*",
        "SELECT (SELECT 1",
        "SELECT * FROM orders; SET ROLE postgres",
    ],
)
def test_nested_commented_and_malformed_smuggling_rejected(sql):
    result = check(sql)
    assert not result.valid, f"expected rejection for: {sql} -> {result.errors}"


@pytest.mark.parametrize(
    "sql",
    [
        # A read-only tautology is still a SELECT: it is allowed, because the
        # defence is statement/table allowlisting plus read-only execution,
        # not escaping of user data (the app never concatenates values).
        "SELECT * FROM orders WHERE email = 'x' OR '1'='1' --'",
        "SELECT/**/ * FROM/**/ orders",
        "SELECT * FROM orders WHERE note = 'it''s fine'",
    ],
)
def test_comments_and_literals_do_not_defeat_the_allowlist(sql):
    result = check(sql)
    assert result.valid, result.errors
