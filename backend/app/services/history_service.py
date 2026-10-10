"""History recording that survives request-scoped rollbacks.

When an API handler raises (e.g. a query execution failure), the request's
session is rolled back — so failure records must be written with their own
session, otherwise the audit trail would disappear exactly when it matters.
"""

from __future__ import annotations

import logging

from app.db.session import get_session_factory
from app.models import QueryHistory

logger = logging.getLogger("querymind.history")


def record_history(
    *,
    user_id: str,
    question: str,
    generated_sql: str,
    execution_status: str,
    connection_id: str | None = None,
    conversation_id: str | None = None,
    execution_time_ms: int | None = None,
    row_count: int | None = None,
    error_message: str | None = None,
) -> str | None:
    session = get_session_factory()()
    try:
        row = QueryHistory(
            user_id=user_id,
            connection_id=connection_id,
            conversation_id=conversation_id,
            question=question,
            generated_sql=generated_sql,
            execution_status=execution_status,
            execution_time_ms=execution_time_ms,
            row_count=row_count,
            error_message=error_message,
        )
        session.add(row)
        session.commit()
        return row.id
    except Exception:
        session.rollback()
        logger.exception("Failed to record query history")
        return None
    finally:
        session.close()
