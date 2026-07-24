"""Recruiter-facing schemas for company-private questions.

correct_key IS present here: recruiters author these questions. The hard
rule forbids it in candidate-facing schemas only.
"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models import Difficulty, QuestionStatus

OPTION_KEYS = ("a", "b", "c", "d")


class QuestionCreate(BaseModel):
    prompt_md: str = Field(min_length=10, max_length=500)
    options: dict[str, str]
    correct_key: str = Field(pattern=r"^[a-d]$")
    explanation_md: str = Field(default="", max_length=2000)
    tags: list[str] = Field(min_length=1, max_length=10)
    difficulty: Difficulty = Difficulty.MEDIUM
    time_limit_seconds: int = Field(default=15, ge=10, le=60)

    @field_validator("options")
    @classmethod
    def _four_options(cls, value: dict[str, str]) -> dict[str, str]:
        if set(value) != set(OPTION_KEYS):
            raise ValueError("options must have exactly the keys a, b, c, d")
        if any(not text.strip() for text in value.values()):
            raise ValueError("options must not be empty")
        return value

    @field_validator("tags")
    @classmethod
    def _normalize_tags(cls, value: list[str]) -> list[str]:
        return sorted({tag.strip().lower() for tag in value if tag.strip()})


class QuestionUpdate(BaseModel):
    prompt_md: str | None = Field(default=None, min_length=10, max_length=500)
    options: dict[str, str] | None = None
    correct_key: str | None = Field(default=None, pattern=r"^[a-d]$")
    explanation_md: str | None = Field(default=None, max_length=2000)
    tags: list[str] | None = Field(default=None, min_length=1, max_length=10)
    difficulty: Difficulty | None = None
    time_limit_seconds: int | None = Field(default=None, ge=10, le=60)
    status: QuestionStatus | None = None

    @field_validator("options")
    @classmethod
    def _four_options(cls, value: dict[str, str] | None) -> dict[str, str] | None:
        if value is not None and set(value) != set(OPTION_KEYS):
            raise ValueError("options must have exactly the keys a, b, c, d")
        return value


class QuestionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    prompt_md: str
    options: dict[str, str]
    correct_key: str
    explanation_md: str
    tags: list[str]
    difficulty: Difficulty
    time_limit_seconds: int
    status: QuestionStatus
    created_at: datetime


class BankQuestionOut(BaseModel):
    """Open-bank question as recruiters browse it. Admin-side only — the bank
    is public content, but this schema must never be reused candidate-facing."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    domain: str
    prompt_md: str
    options: dict[str, str]
    correct_key: str
    explanation_md: str
    tags: list[str]
    difficulty: Difficulty
    time_limit_seconds: int
    blocked: bool = False  # on this company's blocklist


class BankQuestionPage(BaseModel):
    items: list[BankQuestionOut]
    total: int
    tags: list[str]  # all distinct bank tags, for filter UIs
