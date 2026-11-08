import enum
import uuid
from datetime import UTC, datetime, timedelta
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
    """One interview request per application and round.

    Slots are never frozen on the row - both the candidate's picker and the
    booking re-check compute them live from the interviewer's saved
    availability minus Ganek's own bookings (``services.interviews.live_slots``).
    Cancelled rows stay as history; the partial unique index allows one
    non-cancelled row per (application, round), so a cancellation frees its
    round and the next round opens once the latest one is over
    (``services.interviews.create_interview``).
    """

    __tablename__ = "interviews"
    __table_args__ = (
        Index(
            "ix_interviews_application_round_active",
            "application_id",
            "round_number",
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
    # 1-based interview round within the application (0054)
    round_number: Mapped[int] = mapped_column(SmallInteger, default=1, server_default="1")
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
    # room or video link shown to both sides; snapshot of the interviewer's
    # default at request time (0040)
    location: Mapped[str] = mapped_column(String(500), default="")
    # iTIP SEQUENCE of the last invite sent; a reschedule bumps it so the
    # recipients' calendars replace the event, a cancel sends one higher
    ics_sequence: Mapped[int] = mapped_column(SmallInteger, default=0)
    # arq job id for the T-24h reminder (PR ⑧); requeued on reschedule
    reminder_job_id: Mapped[str | None] = mapped_column(String(100))

    application: Mapped["Application"] = relationship()
    interviewer: Mapped["User"] = relationship(lazy="selectin")

    @property
    def interviewer_email(self) -> str:
        return self.interviewer.email

    def is_completed(self, now: datetime | None = None) -> bool:
        """Booked and its end has passed: the round is over and the next may open."""
        if self.status is not InterviewStatus.BOOKED or self.scheduled_start is None:
            return False
        end = self.scheduled_start + timedelta(minutes=self.duration_minutes)
        return end <= (now or datetime.now(UTC))

    @property
    def completed(self) -> bool:
        return self.is_completed()
