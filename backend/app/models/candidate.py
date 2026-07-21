import uuid
from typing import TYPE_CHECKING, Any

from sqlalchemy import ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.application import Application


class Candidate(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A person who applied at a company. Deduplicated by email per company."""

    __tablename__ = "candidates"
    __table_args__ = (UniqueConstraint("company_id", "email"),)

    company_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), index=True
    )
    email: Mapped[str] = mapped_column(String(320))
    name: Mapped[str] = mapped_column(String(200))
    links: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)

    applications: Mapped[list["Application"]] = relationship(back_populates="candidate")
