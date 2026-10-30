import enum
import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.candidate import Candidate
    from app.models.job import Job
    from app.models.quiz import QuizAttempt


class ApplicationStage(enum.StrEnum):
    NEW = "new"
    SCREENING = "screening"
    INTERVIEW = "interview"
    OFFER = "offer"
    HIRED = "hired"
    REJECTED = "rejected"
    WITHDRAWN = "withdrawn"  # candidate-initiated via the status page


class Application(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "applications"
    __table_args__ = (
        UniqueConstraint("job_id", "candidate_id"),
        Index("ix_applications_job_id_stage", "job_id", "stage"),
    )

    company_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), index=True
    )
    job_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"))
    candidate_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("candidates.id", ondelete="CASCADE"))
    cv_object_key: Mapped[str] = mapped_column(String(500))
    cv_filename: Mapped[str] = mapped_column(String(255))
    cv_size: Mapped[int] = mapped_column(Integer)
    message: Mapped[str | None] = mapped_column(Text)
    stage: Mapped[ApplicationStage] = mapped_column(
        Enum(
            ApplicationStage,
            values_callable=lambda e: [m.value for m in e],
            native_enum=False,
            length=20,
        ),
        default=ApplicationStage.NEW,
    )
    source: Mapped[str | None] = mapped_column(String(100))
    # retention clock (G3): stamped on terminal stages, cleared on reopening;
    # the nightly purge measures the company's retention window from here
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # when the row entered its current stage (0035): "longest in stage" sort;
    # every stage writer stamps it, a no-op move leaves it alone
    stage_changed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    # internal rejection reason (0036): a key from services.rejection_reasons
    # plus a free note, set when the row enters rejected or withdrawn and
    # cleared when it leaves; the stage.changed payload keeps the history
    rejection_reason: Mapped[str | None] = mapped_column(String(40))
    rejection_note: Mapped[str | None] = mapped_column(Text)

    candidate: Mapped["Candidate"] = relationship(back_populates="applications")
    job: Mapped["Job"] = relationship()
    quiz_attempts: Mapped[list["QuizAttempt"]] = relationship(
        back_populates="application", order_by="QuizAttempt.created_at"
    )

    @property
    def quiz_attempt(self) -> "QuizAttempt | None":
        """The attempt that counts - the latest; older rows are re-issue history."""
        return self.quiz_attempts[-1] if self.quiz_attempts else None
