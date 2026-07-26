import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator


def _dedupe_preserve_order(items: list[str]) -> list[str]:
    seen: set[str] = set()
    kept: list[str] = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        kept.append(item)
    return kept


class QuestionnaireCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=500)
    shuffle: bool = False
    question_refs: list[str] = Field(
        default_factory=list,
        max_length=200,
        description="Ordered question ids (open-bank slugs or company UUIDs)",
    )

    @field_validator("question_refs")
    @classmethod
    def _validate_refs(cls, value: list[str]) -> list[str]:
        cleaned = [ref.strip() for ref in value if ref.strip()]
        if any(len(ref) > 100 for ref in cleaned):
            raise ValueError("question ref must be <= 100 characters")
        return _dedupe_preserve_order(cleaned)


class QuestionnaireUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=500)
    shuffle: bool | None = None
    question_refs: list[str] | None = Field(default=None, max_length=200)

    @field_validator("question_refs")
    @classmethod
    def _validate_refs(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        cleaned = [ref.strip() for ref in value if ref.strip()]
        if any(len(ref) > 100 for ref in cleaned):
            raise ValueError("question ref must be <= 100 characters")
        return _dedupe_preserve_order(cleaned)


class QuestionnaireOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    description: str
    shuffle: bool
    question_refs: list[str]
    created_at: datetime
    updated_at: datetime
