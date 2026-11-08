from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import DateTime, String, Text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.job import Job
    from app.models.user import User


class Company(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "companies"

    slug: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    logo_url: Mapped[str | None] = mapped_column(String(500))
    website: Mapped[str | None] = mapped_column(String(500))
    socials: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    theme: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    settings: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    # bank question ids this company never wants served, across all its jobs
    blocked_question_ids: Mapped[list[str]] = mapped_column(ARRAY(String(100)), default=list)
    # default screening questions copied into every new job (0039); shape in
    # services.screening.ScreeningQuestion
    screening_questions: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    # default scorecard criteria copied into every new job (0042)
    scorecard_template: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    # operator suspension (0049, services/ops.py): set = public pages answer
    # 503 and every sign-in, session and API key of the tenant is refused
    suspended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    suspension_reason: Mapped[str | None] = mapped_column(String(500))

    users: Mapped[list["User"]] = relationship(back_populates="company")
    jobs: Mapped[list["Job"]] = relationship(back_populates="company")
