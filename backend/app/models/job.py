import enum
import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    false,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.company import Company


class RemotePolicy(enum.StrEnum):
    ONSITE = "onsite"
    HYBRID = "hybrid"
    REMOTE = "remote"


class EmploymentType(enum.StrEnum):
    FULL_TIME = "full_time"
    PART_TIME = "part_time"
    CONTRACT = "contract"
    INTERNSHIP = "internship"


class Seniority(enum.StrEnum):
    INTERN = "intern"
    JUNIOR = "junior"
    MID = "mid"
    SENIOR = "senior"
    LEAD = "lead"
    PRINCIPAL = "principal"


class JobStatus(enum.StrEnum):
    DRAFT = "draft"
    PUBLISHED = "published"
    CLOSED = "closed"


class SalaryPeriod(enum.StrEnum):
    HOUR = "hour"
    DAY = "day"
    WEEK = "week"
    MONTH = "month"
    YEAR = "year"


def _str_enum(enum_cls: type[enum.StrEnum]) -> Enum:
    return Enum(
        enum_cls,
        values_callable=lambda e: [m.value for m in e],
        native_enum=False,
        length=20,
    )


class Job(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "jobs"
    __table_args__ = (
        UniqueConstraint("company_id", "slug"),
        Index("ix_jobs_tags", "tags", postgresql_using="gin"),
    )

    company_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), index=True
    )
    slug: Mapped[str] = mapped_column(String(64))
    title: Mapped[str] = mapped_column(String(200))
    description_md: Mapped[str] = mapped_column(Text, default="")
    location: Mapped[str] = mapped_column(String(200), default="")
    remote_policy: Mapped[RemotePolicy] = mapped_column(
        _str_enum(RemotePolicy), default=RemotePolicy.ONSITE
    )
    employment_type: Mapped[EmploymentType] = mapped_column(
        _str_enum(EmploymentType), default=EmploymentType.FULL_TIME
    )
    salary_min: Mapped[int | None] = mapped_column(Integer)
    salary_max: Mapped[int | None] = mapped_column(Integer)
    salary_currency: Mapped[str | None] = mapped_column(String(3))
    salary_period: Mapped[SalaryPeriod] = mapped_column(
        _str_enum(SalaryPeriod), default=SalaryPeriod.YEAR, server_default="year"
    )
    # Application deadline: surfaces as JSON-LD validThrough for Google Jobs.
    # Advisory unless the team opts in with auto_close (0048): then the hourly
    # worker closes the posting once the closes-on day is over (UTC).
    closes_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    auto_close: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    # job fields (0048): department and seniority and language are public
    # (careers page, feed, embed); the owner and the internal note never are
    department: Mapped[str] = mapped_column(String(100), default="", server_default="")
    seniority: Mapped[Seniority | None] = mapped_column(_str_enum(Seniority), nullable=True)
    # ISO 639-1 code of the posting's language ("en", "pl"); NULL = unset
    language: Mapped[str | None] = mapped_column(String(10), nullable=True)
    owner_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    internal_note: Mapped[str] = mapped_column(Text, default="", server_default="")
    tags: Mapped[list[str]] = mapped_column(ARRAY(String(50)), default=list)
    status: Mapped[JobStatus] = mapped_column(_str_enum(JobStatus), default=JobStatus.DRAFT)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # set by close_job, cleared by publish_job: "days open" for closed jobs
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    quiz_config: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    # per-job screening questions (0039); shape in services.screening
    screening_questions: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    # per-job scorecard criteria (0042)
    scorecard_template: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)

    company: Mapped["Company"] = relationship(back_populates="jobs")
