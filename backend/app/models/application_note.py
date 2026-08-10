import uuid
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.user import User


class ApplicationNote(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Recruiter-internal note; never candidate-visible (test-enforced)."""

    __tablename__ = "application_notes"

    company_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), index=True
    )
    application_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("applications.id", ondelete="CASCADE"), index=True
    )
    # SET NULL so notes outlive departed teammates
    author_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    body: Mapped[str] = mapped_column(Text)

    author: Mapped["User | None"] = relationship(lazy="selectin")

    @property
    def author_email(self) -> str | None:
        return self.author.email if self.author is not None else None
