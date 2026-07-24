import enum
import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import Boolean, DateTime, Enum, Float, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.application import Application


class AttemptStatus(enum.StrEnum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    EXPIRED = "expired"


class QuizAttempt(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One quiz run per application. All timing is server-authoritative."""

    __tablename__ = "quiz_attempts"

    company_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), index=True
    )
    application_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("applications.id", ondelete="CASCADE"), unique=True
    )
    status: Mapped[AttemptStatus] = mapped_column(
        Enum(
            AttemptStatus,
            values_callable=lambda e: [m.value for m in e],
            native_enum=False,
            length=20,
        ),
        default=AttemptStatus.PENDING,
    )
    question_ids: Mapped[list[str]] = mapped_column(ARRAY(String(100)))  # frozen serve order
    # per-question seconds, frozen from the job's quiz_config at creation;
    # NULL = fall back to each question's own time_limit_seconds
    time_limit_seconds: Mapped[int | None] = mapped_column(Integer)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    score: Mapped[float | None] = mapped_column(Float)
    per_tag_scores: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    integrity: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)

    application: Mapped["Application"] = relationship(back_populates="quiz_attempt")
    answers: Mapped[list["AttemptAnswer"]] = relationship(
        back_populates="attempt", order_by="AttemptAnswer.served_at"
    )


class AttemptAnswer(UUIDPrimaryKeyMixin, Base):
    """One served question within an attempt.

    ``answered_at`` set = resolved; ``answer_key`` NULL on a resolved row
    means the candidate never answered before the deadline.
    """

    __tablename__ = "attempt_answers"

    attempt_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("quiz_attempts.id", ondelete="CASCADE"), index=True
    )
    question_id: Mapped[str] = mapped_column(ForeignKey("questions.id", ondelete="RESTRICT"))
    option_order: Mapped[list[str]] = mapped_column(ARRAY(String(1)))  # as served
    served_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    deadline_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    answered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    answer_key: Mapped[str | None] = mapped_column(String(1))
    is_correct: Mapped[bool] = mapped_column(Boolean, default=False)

    attempt: Mapped["QuizAttempt"] = relationship(back_populates="answers")
