import enum
import uuid
from datetime import date, datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
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


class CvScanStatus(enum.StrEnum):
    """Virus scan state of an application's CV (0055). NULL on the row means
    not scanned: no CV, scanning not configured, or uploaded before 0055."""

    PENDING = "pending"
    CLEAN = "clean"
    INFECTED = "infected"
    ERROR = "error"  # the scanner could not decide after its retries


# an application nobody is working on any more drops its pointers
CLOSED_STAGES = (ApplicationStage.REJECTED, ApplicationStage.WITHDRAWN, ApplicationStage.HIRED)


class Application(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "applications"
    __table_args__ = (
        UniqueConstraint("job_id", "candidate_id"),
        Index("ix_applications_job_id_stage", "job_id", "stage"),
        # the worker's sweep for scans whose enqueue was lost (0055)
        Index(
            "ix_applications_cv_scan_pending",
            "created_at",
            postgresql_where=text("cv_scan_status = 'pending'"),
        ),
    )

    company_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), index=True
    )
    job_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"))
    candidate_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("candidates.id", ondelete="CASCADE"))
    # all three NULL together for an application created without a CV by an
    # internal caller (CSV import, screen link, connectors; 0046). The public
    # apply form still requires one.
    cv_object_key: Mapped[str | None] = mapped_column(String(500))
    cv_filename: Mapped[str | None] = mapped_column(String(255))
    cv_size: Mapped[int | None] = mapped_column(Integer)
    # ClamAV verdict for the CV (0055, services.cv_scan); an infected CV is
    # never handed out (download, review link, webhook, DSAR)
    cv_scan_status: Mapped[CvScanStatus | None] = mapped_column(
        Enum(
            CvScanStatus,
            values_callable=lambda e: [m.value for m in e],
            native_enum=False,
            length=16,
        )
    )
    cv_scan_signature: Mapped[str | None] = mapped_column(String(200))
    cv_scanned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    message: Mapped[str | None] = mapped_column(Text)
    # answers to the job's screening questions with a snapshot of each
    # question (0039, GIN-indexed); written once at apply time
    screening_answers: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
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
    # the decision date the team promised this candidate (0047); NULL =
    # applied + the company's decision window (services.decision_dates)
    decision_expected_on: Mapped[date | None] = mapped_column(Date)

    candidate: Mapped["Candidate"] = relationship(back_populates="applications")
    job: Mapped["Job"] = relationship()
    quiz_attempts: Mapped[list["QuizAttempt"]] = relationship(
        back_populates="application", order_by="QuizAttempt.created_at"
    )

    @property
    def quiz_attempt(self) -> "QuizAttempt | None":
        """The attempt that counts - the latest; older rows are re-issue history."""
        return self.quiz_attempts[-1] if self.quiz_attempts else None
