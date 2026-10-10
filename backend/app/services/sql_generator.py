"""Natural language -> SQL pipeline: schema, prompt, model, validation."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.core.errors import ApiError
from app.services.ai_service import AIProviderError, AIService, get_ai_service
from app.services.schema_service import SchemaInfo
from app.services.sql_validator import ValidationResult, validate_sql


@dataclass
class GenerationOutcome:
    sql: str | None
    explanation: str
    clarification: str | None
    validation: ValidationResult | None
    model: str = ""
    latency_ms: int = 0
    schema_tables: int = 0
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "success": self.sql is not None and (self.validation is None or self.validation.valid),
            "sql": self.sql,
            "explanation": self.explanation,
            "clarification": self.clarification,
            "validation": self.validation.as_dict() if self.validation else None,
            "model": self.model,
            "generation_time_ms": self.latency_ms,
            "schema_tables": self.schema_tables,
            "errors": self.errors,
        }


def generate_sql_from_question(
    *,
    question: str,
    schema: SchemaInfo,
    history: list[dict[str, str]] | None = None,
    ai: AIService | None = None,
) -> GenerationOutcome:
    question = (question or "").strip()
    if not question:
        raise ApiError(400, "invalid_question", "Please enter a question.")

    service = ai or get_ai_service()
    try:
        generation = service.generate_sql(
            question=question,
            schema_context=schema.prompt_context(),
            history=history,
        )
    except AIProviderError as exc:
        raise exc.to_api_error() from exc

    if generation.clarification and not generation.sql:
        return GenerationOutcome(
            sql=None,
            explanation=generation.explanation,
            clarification=generation.clarification,
            validation=None,
            model=generation.model,
            latency_ms=generation.latency_ms,
            schema_tables=len(schema.tables),
        )

    if not generation.sql:
        raise ApiError(
            502,
            "invalid_model_output",
            "The model did not return SQL for that question. Try rephrasing it.",
        )

    validation = validate_sql(
        generation.sql,
        allowed_tables=schema.allowlist(),
        allowed_schemas=schema.schema_set(),
    )
    outcome = GenerationOutcome(
        sql=generation.sql if validation.valid else generation.sql,
        explanation=generation.explanation,
        clarification=None,
        validation=validation,
        model=generation.model,
        latency_ms=generation.latency_ms,
        schema_tables=len(schema.tables),
    )
    if not validation.valid:
        outcome.errors = list(validation.errors)
    return outcome


def validate_against_schema(sql: str, schema: SchemaInfo) -> ValidationResult:
    return validate_sql(
        sql,
        allowed_tables=schema.allowlist(),
        allowed_schemas=schema.schema_set(),
    )
