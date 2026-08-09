import enum
import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Enum, ForeignKey, Index, SmallInteger, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.application import Application
    from app.models.user import User


class InterviewStatus(enum.StrEnum):
    PENDING = "pending"  # invite sent, candidate hasn't picked a slot
    BOOKED = "booked"
    CANCELLED = "cancelled"


class Interview(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One interview request per application (single-round v1).

    Slots are never frozen on the row — both the candidate's picker and the
    booking re-check compute them live from the interviewer's saved
    availability + Google free/busy (``services.interviews.live_slots``).
    Cancelled rows stay as history; the partial unique index allows a fresh
    request after a cancellation.
    """

    __tablename__ = "interviews"
    __table_args__ = (
        Index(
            "ix_interviews_application_active",
            "application_id",
            unique=True,
            postgresql_where=text("status != 'cancelled'"),
        ),
    )

    company_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), index=True
    )
    application_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("applications.id", ondelete="CASCADE"), index=True
    )
    interviewer_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    title: Mapped[str] = mapped_column(String(200), default="Hiring manager interview")
    description: Mapped[str] = mapped_column(Text, default="")
    duration_minutes: Mapped[int] = mapped_column(SmallInteger)
    timezone: Mapped[str] = mapped_column(String(60))  # IANA, interviewer-side
    status: Mapped[InterviewStatus] = mapped_column(
        Enum(
            InterviewStatus,
            values_callable=lambda e: [m.value for m in e],
            native_enum=False,
            length=20,
        ),
        default=InterviewStatus.PENDING,
    )
    scheduled_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    google_event_id: Mapped[str | None] = mapped_column(String(300))
    meet_url: Mapped[str | None] = mapped_column(String(500))
    # arq job id for the T-24h reminder (PR ⑧); requeued on reschedule
    reminder_job_id: Mapped[str | None] = mapped_column(String(100))

    application: Mapped["Application"] = relationship()
    interviewer: Mapped["User"] = relationship(lazy="selectin")

    @property
    def interviewer_email(self) -> str:
        return self.interviewer.email
