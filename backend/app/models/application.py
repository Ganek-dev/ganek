import enum
import uuid
from typing import TYPE_CHECKING

from sqlalchemy import Enum, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.candidate import Candidate
    from app.models.job import Job


class ApplicationStage(enum.StrEnum):
    NEW = "new"
    SCREENING = "screening"
    INTERVIEW = "interview"
    OFFER = "offer"
    HIRED = "hired"
    REJECTED = "rejected"


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

    candidate: Mapped["Candidate"] = relationship(back_populates="applications")
    job: Mapped["Job"] = relationship()
