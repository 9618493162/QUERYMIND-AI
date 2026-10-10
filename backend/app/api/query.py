"""Query pipeline: generate, validate, execute."""

from __future__ import annotations

import time

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.deps import get_current_user
from app.core.errors import ApiError
from app.core.rate_limit import rate_limit
from app.db.session import get_db
from app.models import Conversation, ConversationMessage, QueryHistory, User
from app.schemas import ExecuteIn, GenerateIn, ValidateIn
from app.services import connection_service, schema_service, sql_generator
from app.services.chart_service import recommend_chart
from app.services.query_executor import execute_readonly

router = APIRouter()


def _schema_for(db: Session, user: User, connection_id: str):
    conn = connection_service.get_owned_connection(db, user, connection_id)
    engine = connection_service.engine_for_connection(conn, read_only=True)
    try:
        info = schema_service.get_schema(engine, connection_id=connection_id)
    finally:
        engine.dispose()
    return conn, info


def _history_messages(db: Session, conversation_id: str | None, user: User) -> list[dict[str, str]]:
    if not conversation_id:
        return []
    conv = db.get(Conversation, conversation_id)
    if conv is None or conv.user_id != user.id:
        return []
    msgs = (
        db.execute(
            select(ConversationMessage)
            .where(ConversationMessage.conversation_id == conv.id)
            .order_by(ConversationMessage.created_at.desc())
            .limit(6)
        )
        .scalars()
        .all()
    )
    return [{"role": m.role, "content": m.content} for m in reversed(msgs)]


@router.post("/generate")
def generate(
    payload: GenerateIn,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    rate_limit(request, "query-generate", settings.query_rate_limit_per_minute)
    _conn, schema = _schema_for(db, user, payload.connection_id)
    history = _history_messages(db, payload.conversation_id, user)

    outcome = sql_generator.generate_sql_from_question(
        question=payload.question,
        schema=schema,
        history=history,
    )

    status = "generated" if outcome.sql else "needs_clarification"
    if outcome.sql and outcome.validation and not outcome.validation.valid:
        status = "rejected"
    history_row = QueryHistory(
        user_id=user.id,
        connection_id=payload.connection_id,
        conversation_id=payload.conversation_id,
        question=payload.question,
        generated_sql=outcome.sql or "",
        execution_status=status,
        error_message="; ".join(outcome.errors) if outcome.errors else None,
    )
    db.add(history_row)
    db.commit()

    result = outcome.to_dict()
    result["history_id"] = history_row.id
    return result


@router.post("/validate")
def validate(
    payload: ValidateIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    _conn, schema = _schema_for(db, user, payload.connection_id)
    validation = sql_generator.validate_against_schema(payload.sql, schema)
    return {"success": True, "validation": validation.as_dict()}


@router.post("/execute")
def execute(
    payload: ExecuteIn,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    rate_limit(request, "query-execute", settings.query_rate_limit_per_minute)
    conn, schema = _schema_for(db, user, payload.connection_id)

    # Re-validate at execution time — never trust earlier validation or the model.
    validation = sql_generator.validate_against_schema(payload.sql, schema)
    if not validation.valid:
        raise ApiError(
            400,
            "sql_rejected",
            "The query failed security validation and was not executed.",
            details=validation.errors,
        )

    started = time.perf_counter()
    try:
        result = execute_readonly(
            payload.sql,
            host=conn.host,
            port=conn.port,
            database=conn.database_name,
            username=conn.username,
            password=connection_service.connection_password(conn),
            ssl_mode=conn.ssl_mode,
            max_rows=payload.max_rows,
        )
    except ApiError as exc:
        from app.services.history_service import record_history

        record_history(
            user_id=user.id,
            connection_id=payload.connection_id,
            conversation_id=payload.conversation_id,
            question=payload.question or "(direct SQL execution)",
            generated_sql=payload.sql,
            execution_status="failed",
            error_message=exc.message,
        )
        raise

    elapsed = int((time.perf_counter() - started) * 1000)
    history_row = QueryHistory(
        user_id=user.id,
        connection_id=payload.connection_id,
        conversation_id=payload.conversation_id,
        question=payload.question or "(direct SQL execution)",
        generated_sql=payload.sql,
        execution_status="success",
        execution_time_ms=result.execution_time_ms or elapsed,
        row_count=result.row_count,
    )
    db.add(history_row)
    db.commit()

    chart = recommend_chart(result.columns, result.rows)
    payload_dict = result.to_dict()
    payload_dict["chart"] = chart
    payload_dict["history_id"] = history_row.id
    return payload_dict
