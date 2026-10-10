"""Conversations and contextual follow-up questions."""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.deps import get_current_user
from app.core.errors import ApiError
from app.core.rate_limit import rate_limit
from app.db.session import get_db
from app.models import Conversation, ConversationMessage, User
from app.schemas import ConversationIn, MessageIn
from app.services import connection_service, schema_service, sql_generator
from app.services.ai_service import get_ai_service

router = APIRouter()

MAX_CONTEXT_MESSAGES = 6


def _conv_out(c: Conversation) -> dict:
    return {
        "id": c.id,
        "connection_id": c.connection_id,
        "title": c.title,
        "created_at": c.created_at.isoformat() if c.created_at else None,
        "updated_at": c.updated_at.isoformat() if c.updated_at else None,
    }


def _msg_out(m: ConversationMessage) -> dict:
    meta = None
    if m.metadata_json:
        try:
            meta = json.loads(m.metadata_json)
        except json.JSONDecodeError:
            meta = None
    return {
        "id": m.id,
        "role": m.role,
        "content": m.content,
        "metadata": meta,
        "created_at": m.created_at.isoformat() if m.created_at else None,
    }


def _owned(db: Session, user: User, conversation_id: str) -> Conversation:
    conv = db.get(Conversation, conversation_id)
    if conv is None or conv.user_id != user.id:
        raise ApiError(404, "not_found", "Conversation not found.")
    return conv


@router.get("")
def list_conversations(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    rows = (
        db.execute(
            select(Conversation)
            .where(Conversation.user_id == user.id)
            .order_by(Conversation.updated_at.desc())
            .limit(50)
        )
        .scalars()
        .all()
    )
    return {"success": True, "items": [_conv_out(c) for c in rows]}


@router.post("", status_code=201)
def create_conversation(
    payload: ConversationIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    conv = Conversation(
        user_id=user.id,
        connection_id=payload.connection_id,
        title=payload.title.strip() or "New conversation",
    )
    db.add(conv)
    db.commit()
    return {"success": True, "conversation": _conv_out(conv)}


@router.get("/{conversation_id}")
def get_conversation(
    conversation_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    conv = _owned(db, user, conversation_id)
    messages = (
        db.execute(
            select(ConversationMessage)
            .where(ConversationMessage.conversation_id == conv.id)
            .order_by(ConversationMessage.created_at.asc())
            .limit(200)
        )
        .scalars()
        .all()
    )
    return {
        "success": True,
        "conversation": _conv_out(conv),
        "messages": [_msg_out(m) for m in messages],
    }


@router.delete("/{conversation_id}")
def delete_conversation(
    conversation_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    conv = _owned(db, user, conversation_id)
    db.delete(conv)
    db.commit()
    return {"success": True}


@router.post("/{conversation_id}/messages")
def post_message(
    conversation_id: str,
    payload: MessageIn,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    rate_limit(request, "query-generate", settings.query_rate_limit_per_minute)
    conv = _owned(db, user, conversation_id)
    conn = connection_service.get_owned_connection(db, user, payload.connection_id)

    engine = connection_service.engine_for_connection(conn, read_only=True)
    try:
        schema = schema_service.get_schema(engine, connection_id=conn.id)
    finally:
        engine.dispose()

    prior = (
        db.execute(
            select(ConversationMessage)
            .where(ConversationMessage.conversation_id == conv.id)
            .order_by(ConversationMessage.created_at.desc())
            .limit(MAX_CONTEXT_MESSAGES)
        )
        .scalars()
        .all()
    )
    history = [{"role": m.role, "content": m.content} for m in reversed(prior)]

    # Prior conversation text is untrusted data: strip obvious instruction markers.
    safe_question = payload.question.replace("\n", " ").strip()

    user_msg = ConversationMessage(
        conversation_id=conv.id, role="user", content=safe_question
    )
    db.add(user_msg)

    try:
        outcome = sql_generator.generate_sql_from_question(
            question=safe_question, schema=schema, history=history
        )
    except ApiError:
        # The user message is added to this request's session but the error
        # aborts the transaction — re-raise and let the client surface it.
        raise

    if outcome.clarification and not outcome.sql:
        content = outcome.clarification
        meta = {"kind": "clarification", "model": outcome.model}
    else:
        content = outcome.explanation or "Here is the generated query."
        meta = {
            "kind": "sql",
            "sql": outcome.sql,
            "explanation": outcome.explanation,
            "validation": outcome.validation.as_dict() if outcome.validation else None,
            "model": outcome.model,
            "generation_time_ms": outcome.latency_ms,
        }
    assistant = ConversationMessage(
        conversation_id=conv.id,
        role="assistant",
        content=content,
        metadata_json=json.dumps(meta),
    )
    db.add(assistant)
    if conv.title == "New conversation":
        conv.title = safe_question[:80]
    conv.connection_id = conn.id
    db.commit()

    return {
        "success": True,
        "user_message": _msg_out(user_msg),
        "assistant_message": _msg_out(assistant),
        "sql": outcome.sql,
        "explanation": outcome.explanation,
        "clarification": outcome.clarification,
        "validation": outcome.validation.as_dict() if outcome.validation else None,
        "model": outcome.model,
    }
