import uuid
from datetime import date, datetime

from sqlalchemy import Date, DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class Task(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Manual to-do on the dashboard queue ("Call Marta about the offer").

    Derived queue items (new applicants, drafts without quiz, …) are
    computed live and never stored here.
    """

    __tablename__ = "tasks"

    company_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), index=True
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    assignee_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    title: Mapped[str] = mapped_column(String(200))
    note: Mapped[str] = mapped_column(Text, default="")
    due_date: Mapped[date | None] = mapped_column(Date)
    done_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
