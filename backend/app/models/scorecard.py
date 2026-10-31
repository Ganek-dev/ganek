import enum
import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import DateTime, Enum, ForeignKey, Index, Text, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.application import Application
    from app.models.interview import Interview
    from app.models.job import Job
    from app.models.user import User


class Recommendation(enum.StrEnum):
    STRONG_NO = "strong_no"
    NO = "no"
    YES = "yes"
    STRONG_YES = "strong_yes"


class Scorecard(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One reviewer's structured feedback on one application (0042).

    The row doubles as the request: it exists from the moment a reviewer is
    asked (``requested_at``) and is filled in on submit. The criteria are
    snapshotted at request time so later template edits never rewrite a
    submitted scorecard. Visualization only - nothing here gates a candidate.
    """

    __tablename__ = "scorecards"
    __table_args__ = (
        Index(
            "uq_scorecards_application_reviewer",
            "application_id",
            "reviewer_user_id",
            unique=True,
            postgresql_where=text("reviewer_user_id IS NOT NULL"),
        ),
        Index(
            "ix_scorecards_company_reviewer_submitted",
            "company_id",
            "reviewer_user_id",
            "submitted_at",
        ),
        Index("ix_scorecards_company_application", "company_id", "application_id"),
    )

    company_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("companies.id", ondelete="CASCADE"))
    application_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("applications.id", ondelete="CASCADE")
    )
    job_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"))
    reviewer_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    requested_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    dismissed_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    interview_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("interviews.id", ondelete="SET NULL")
    )
    requested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    # when the reviewer's turn starts (interview end, or request time)
    due_from: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    reminded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    dismissed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    declined_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # [{"id", "label", ...}] copied from the job template at request time
    criteria_snapshot: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    # criterion id -> 1..5
    ratings: Mapped[dict[str, int]] = mapped_column(JSONB, default=dict)
    recommendation: Mapped[Recommendation | None] = mapped_column(
        Enum(
            Recommendation,
            values_callable=lambda e: [m.value for m in e],
            native_enum=False,
            length=16,
        )
    )
    comment: Mapped[str | None] = mapped_column(Text)

    application: Mapped["Application"] = relationship()
    job: Mapped["Job"] = relationship()
    reviewer: Mapped["User | None"] = relationship(foreign_keys=[reviewer_user_id], lazy="selectin")
    requested_by: Mapped["User | None"] = relationship(
        foreign_keys=[requested_by_user_id], lazy="selectin"
    )
    interview: Mapped["Interview | None"] = relationship()
