"""Independent SQL security validation.

Every model-generated (or user-edited) statement is parsed with sqlglot using
the PostgreSQL dialect and checked against an explicit allowlist of query
constructs. This runs in application code, separately from the model, and in
addition to database-level read-only permissions.

Rejected:
- multiple statements
- anything that is not a single SELECT / WITH ... SELECT (or set operation)
- SELECT INTO and data-modifying CTEs
- DDL/DCL/admin statements (DROP, ALTER, CREATE, TRUNCATE, GRANT, REVOKE, ...)
- file/network/admin functions (pg_read_file, dblink, lo_*, COPY, CALL, ...)
- references to tables/schemas outside the inspected schema allowlist
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

import sqlglot
from sqlglot import exp

MAX_SQL_LENGTH = 20_000

# Functions that must never appear anywhere in a generated query.
FORBIDDEN_FUNCTIONS = {
    "pg_read_file", "pg_read_binary_file", "pg_read_server_files", "pg_ls_dir",
    "pg_ls_logdir", "pg_ls_waldir", "pg_stat_file", "pg_write_file",
    "pg_terminate_backend", "pg_cancel_backend", "pg_reload_conf",
    "pg_create_restore_point", "pg_switch_wal", "pg_backup_start", "pg_backup_stop",
    "lo_import", "lo_export", "lo_unlink",
    "dblink", "dblink_connect", "dblink_exec", "dblink_send_query", "dblink_open",
    "dblink_fetch", "dblink_close", "dblink_disconnect",
    "query_to_xml", "query_to_xml_and_xmlschema", "schema_to_xml",
    "database_to_xml", "table_to_xml",
    "copy", "call", "nextval", "setval", "currval_ops_write",
    "pg_advisory_lock", "pg_advisory_unlock", "pg_logical_emit_message",
    "pg_create_subscription", "pg_drop_replication_slot",
    "pg_promote", "pg_reload_conf",
    "set_config", "current_setting_write",
    "pg_sleep", "pg_sleep_for", "pg_sleep_until",
    "wait_for_signal", "pg_export_snapshot",
    "ord", "xml_send",  # rarely needed but not for analytics
}

# Statement classes sqlglot maps to generic Command when it cannot parse them.
_ALLOWED_ROOTS = (exp.Select, exp.Union, exp.Intersect, exp.Except, exp.Subquery)


@dataclass
class ValidationResult:
    valid: bool
    errors: list[str] = field(default_factory=list)
    statement_type: str | None = None
    tables: list[str] = field(default_factory=list)
    functions: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "valid": self.valid,
            "errors": self.errors,
            "statement_type": self.statement_type,
            "tables": self.tables,
            "functions": self.functions,
        }


def _norm(name: str) -> str:
    return name.strip().strip('"').lower()


def _collect_cte_names(node: exp.Expression) -> set[str]:
    names: set[str] = set()
    for cte in node.find_all(exp.CTE):
        alias = cte.alias
        if alias:
            names.add(_norm(alias))
    return names


def validate_sql(
    sql: str,
    *,
    allowed_tables: dict[str, set[str]] | None = None,
    allowed_schemas: set[str] | None = None,
    allow_multiple_statements: bool = False,
) -> ValidationResult:
    """Validate a SQL string. Returns a ValidationResult (never raises for bad SQL)."""
    result = ValidationResult(valid=False)

    if not sql or not sql.strip():
        result.errors.append("SQL is empty.")
        return result
    if len(sql) > MAX_SQL_LENGTH:
        result.errors.append(f"SQL exceeds the maximum length of {MAX_SQL_LENGTH} characters.")
        return result

    # Reject null bytes and stacked-statement separators hidden in odd encodings.
    if "\x00" in sql:
        result.errors.append("SQL contains invalid characters.")

    try:
        statements = sqlglot.parse(sql, dialect="postgres")
    except Exception as exc:
        result.errors.append(f"SQL could not be parsed as PostgreSQL: {exc}")
        return result

    statements = [s for s in statements if s is not None]
    if not statements:
        result.errors.append("SQL is empty.")
        return result
    if len(statements) > 1 and not allow_multiple_statements:
        result.errors.append("Multiple SQL statements are not allowed.")
        return result

    statement = statements[0]
    result.statement_type = type(statement).__name__

    # --- root statement must be a read-only query -----------------------------
    if isinstance(statement, exp.Command):
        result.errors.append(
            "Only read-only SELECT statements are allowed "
            "(the statement could not be recognized as a query)."
        )
        return result
    if not isinstance(statement, _ALLOWED_ROOTS):
        result.errors.append(
            f"Statement type '{type(statement).__name__}' is not allowed. Only SELECT queries are permitted."
        )
        return result
    if isinstance(statement, exp.Subquery):
        statement = statement.this if isinstance(statement.this, exp.Query) else statement

    # --- SELECT INTO (materializes a table) -----------------------------------
    for node in statement.find_all(exp.Select):
        if node.args.get("into"):
            result.errors.append("SELECT INTO is not allowed.")
            break

    # --- data-modifying CTEs ---------------------------------------------------
    for cte in statement.find_all(exp.CTE):
        inner = cte.this
        if isinstance(inner, (exp.Insert, exp.Update, exp.Delete, exp.Merge)):
            result.errors.append("Data-modifying CTEs are not allowed.")
            break
        if isinstance(inner, exp.Select) and inner.args.get("into"):
            result.errors.append("SELECT INTO inside a CTE is not allowed.")
            break

    # --- MERGE / INSERT / UPDATE / DELETE anywhere -----------------------------
    for bad in (exp.Insert, exp.Update, exp.Delete, exp.Merge):
        if any(isinstance(n, bad) for n in statement.walk()):
            result.errors.append(f"{type(bad).__name__} statements are not allowed.")
            break

    # --- forbidden functions ----------------------------------------------------
    called: set[str] = set()
    for fn in statement.find_all(exp.Anonymous, exp.Func):
        name = None
        if isinstance(fn, exp.Anonymous):
            name = fn.name
        else:
            name = fn.sql_names()[0] if fn.sql_names() else fn.__class__.__name__
        if not name:
            continue
        fname = _norm(name)
        called.add(fname)
        if fname in FORBIDDEN_FUNCTIONS:
            result.errors.append(f"Function '{fname}()' is not permitted.")
    result.functions = sorted(called)

    # --- table allowlist --------------------------------------------------------
    tables: set[str] = set()
    cte_names = _collect_cte_names(statement)
    if allowed_tables is not None:
        for tbl in statement.find_all(exp.Table):
            if tbl.find_ancestor(exp.CTE) is not None and not tbl.name:
                continue
            schema = tbl.db
            name = tbl.name
            if not name:
                continue
            key = f"{_norm(schema)}.{_norm(name)}" if schema else _norm(name)
            tables.add(key)
            if _norm(name) in cte_names:
                continue
            if schema and allowed_schemas is not None and _norm(schema) not in allowed_schemas:
                result.errors.append(f"Access to schema '{schema}' is not permitted.")
                continue
            if allowed_schemas is not None and not schema:
                # unqualified: allowed only if it exists in any allowed schema
                if not any(_norm(name) in t for t in allowed_tables.values()):
                    result.errors.append(f"Table '{name}' was not found in the inspected schema.")
                continue
            allowed = allowed_tables.get(_norm(schema), set()) if schema else set()
            if schema and _norm(name) not in allowed:
                result.errors.append(
                    f"Table '{schema}.{name}' was not found in the inspected schema."
                )
    else:
        for tbl in statement.find_all(exp.Table):
            if tbl.name:
                schema = tbl.db
                tables.add(f"{_norm(schema)}.{_norm(tbl.name)}" if schema else _norm(tbl.name))
    result.tables = sorted(tables)

    # --- dangerous raw patterns the parser may not surface ---------------------
    raw = sql.lower()
    if re.search(r"\binto\s+table\b", raw):
        result.errors.append("SELECT INTO is not allowed.")
    if re.search(r"\bcopy\s*\(", raw) or re.search(r"^\s*copy\b", raw):
        result.errors.append("COPY is not permitted.")

    result.valid = not result.errors
    return result
