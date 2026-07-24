import enum
import uuid
from typing import Any

from sqlalchemy import Enum, ForeignKey, Index, Integer, SmallInteger, String, Text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin

# Difficulty is a 1–5 scale (5-dot UI: ≤2 easy-ish, 3 medium, ≥4 hard).
# Legacy 3-level values map as easy→2, medium→3, hard→4 (migration 0008).
MIN_DIFFICULTY = 1
MAX_DIFFICULTY = 5


class QuestionStatus(enum.StrEnum):
    ACTIVE = "active"
    RETIRED = "retired"


class QuestionSource(enum.StrEnum):
    SEED = "seed"
    COMPANY = "company"


def _str_enum(enum_cls: type[enum.StrEnum]) -> Enum:
    return Enum(
        enum_cls,
        values_callable=lambda e: [m.value for m in e],
        native_enum=False,
        length=20,
    )


class Question(TimestampMixin, Base):
    """A screening question.

    ``correct_key`` must NEVER appear in any candidate-facing schema.
    Global bank questions (from questions/*.yaml) have company_id NULL and
    a stable human-authored slug id; company questions are tenant-scoped.
    """

    __tablename__ = "questions"
    __table_args__ = (Index("ix_questions_tags", "tags", postgresql_using="gin"),)

    id: Mapped[str] = mapped_column(String(100), primary_key=True)
    company_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), index=True
    )
    domain: Mapped[str] = mapped_column(String(50), index=True)
    tags: Mapped[list[str]] = mapped_column(ARRAY(String(50)), default=list)
    difficulty: Mapped[int] = mapped_column(SmallInteger)  # 1–5, CHECK-enforced
    prompt_md: Mapped[str] = mapped_column(Text)
    options: Mapped[dict[str, Any]] = mapped_column(JSONB)  # {"a": md, "b": md, ...}
    correct_key: Mapped[str] = mapped_column(String(1))
    explanation_md: Mapped[str] = mapped_column(Text, default="")
    time_limit_seconds: Mapped[int] = mapped_column(Integer, default=15)
    locale: Mapped[str] = mapped_column(String(10), default="en")
    status: Mapped[QuestionStatus] = mapped_column(
        _str_enum(QuestionStatus), default=QuestionStatus.ACTIVE
    )
    source: Mapped[QuestionSource] = mapped_column(
        _str_enum(QuestionSource), default=QuestionSource.SEED
    )
