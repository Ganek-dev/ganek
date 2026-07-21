import enum
import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import DateTime, Enum, ForeignKey, Index, Integer, String, Text, UniqueConstraint
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


class JobStatus(enum.StrEnum):
    DRAFT = "draft"
    PUBLISHED = "published"
    CLOSED = "closed"


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
    tags: Mapped[list[str]] = mapped_column(ARRAY(String(50)), default=list)
    status: Mapped[JobStatus] = mapped_column(_str_enum(JobStatus), default=JobStatus.DRAFT)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    quiz_config: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)

    company: Mapped["Company"] = relationship(back_populates="jobs")
