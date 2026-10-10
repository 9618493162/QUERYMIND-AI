"""Pydantic request/response schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# --- auth -------------------------------------------------------------------

class RegisterIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)


class LoginIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class UserOut(BaseModel):
    id: str
    name: str
    email: EmailStr
    created_at: datetime | None = None


# --- connections -------------------------------------------------------------

class ConnectionIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    database_type: str = Field(default="postgresql", max_length=32)
    host: str = Field(min_length=1, max_length=255)
    port: int = Field(default=5432, ge=1, le=65535)
    database_name: str = Field(min_length=1, max_length=255)
    username: str = Field(min_length=1, max_length=255)
    password: str = Field(default="", max_length=512)
    ssl_mode: Literal["disable", "allow", "prefer", "require", "verify-ca", "verify-full"] = "prefer"


class ConnectionOut(BaseModel):
    id: str
    name: str
    database_type: str
    host: str
    port: int
    database_name: str
    username: str
    ssl_mode: str
    has_password: bool
    created_at: datetime | None = None
    updated_at: datetime | None = None


class TestConnectionIn(ConnectionIn):
    pass


class TestConnectionOut(BaseModel):
    success: bool
    message: str
    server_version: str | None = None
    latency_ms: int | None = None


# --- query -------------------------------------------------------------------

class GenerateIn(BaseModel):
    connection_id: str
    question: str = Field(min_length=1, max_length=2000)
    conversation_id: str | None = None


class ValidateIn(BaseModel):
    connection_id: str
    sql: str = Field(min_length=1, max_length=20000)


class ExecuteIn(BaseModel):
    connection_id: str
    sql: str = Field(min_length=1, max_length=20000)
    question: str = Field(default="", max_length=2000)
    conversation_id: str | None = None
    max_rows: int | None = Field(default=None, ge=1, le=10000)


class ExecuteOut(BaseModel):
    success: bool
    columns: list[dict[str, str]]
    rows: list[list[Any]]
    metadata: dict[str, Any]
    explanation: str | None = None
    chart: dict[str, Any] | None = None
    history_id: str | None = None


# --- history ------------------------------------------------------------------

class HistoryOut(BaseModel):
    id: str
    connection_id: str | None
    conversation_id: str | None
    question: str
    generated_sql: str
    execution_status: str
    execution_time_ms: int | None
    row_count: int | None
    error_message: str | None
    created_at: datetime


# --- saved queries ------------------------------------------------------------

class SavedQueryIn(BaseModel):
    connection_id: str | None = None
    title: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=4000)
    natural_language_question: str = Field(default="", max_length=2000)
    sql_query: str = Field(min_length=1, max_length=20000)
    tags: list[str] = Field(default_factory=list)
    is_favorite: bool = False


class SavedQueryPatch(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=4000)
    natural_language_question: str | None = Field(default=None, max_length=2000)
    sql_query: str | None = Field(default=None, min_length=1, max_length=20000)
    tags: list[str] | None = None
    is_favorite: bool | None = None


class SavedQueryOut(BaseModel):
    id: str
    connection_id: str | None
    title: str
    description: str | None
    natural_language_question: str
    sql_query: str
    tags: list[str]
    is_favorite: bool
    created_at: datetime
    updated_at: datetime


# --- conversations -------------------------------------------------------------

class ConversationIn(BaseModel):
    connection_id: str | None = None
    title: str = Field(default="New conversation", max_length=200)


class MessageIn(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    connection_id: str


class MessageOut(BaseModel):
    id: str
    role: str
    content: str
    metadata: dict[str, Any] | None = None
    created_at: datetime


class ConversationOut(BaseModel):
    id: str
    connection_id: str | None
    title: str
    created_at: datetime
    updated_at: datetime


# --- settings ------------------------------------------------------------------

class SettingsIn(BaseModel):
    theme: Literal["light", "dark", "system"] = "system"
    default_chart_type: Literal["auto", "bar", "line", "pie", "table"] = "auto"
    default_row_limit: int = Field(default=500, ge=10, le=10000)


class SettingsOut(SettingsIn):
    user_id: str | None = None


# --- analytics ------------------------------------------------------------------

class ChartRecommendationIn(BaseModel):
    columns: list[dict[str, str]]
    rows: list[list[Any]] = Field(default_factory=list)


class Page(BaseModel):
    items: list[Any]
    total: int
    page: int
    page_size: int
