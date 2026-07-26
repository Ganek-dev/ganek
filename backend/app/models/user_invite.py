import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Enum, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.user import UserRole

if TYPE_CHECKING:
    from app.models.company import Company


class UserInvite(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A pending email invite to join a company's team.

    Rows only exist while an invite is outstanding: accepting one creates
    the ``User`` and deletes the row; revoking deletes it outright. The
    signed invite token carries the row id; ``expires_at`` is the
    authoritative deadline (resend pushes it forward without changing the
    already-emailed token).
    """

    __tablename__ = "user_invites"
    __table_args__ = (UniqueConstraint("company_id", "email"),)

    company_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), index=True
    )
    email: Mapped[str] = mapped_column(String(320), index=True)
    role: Mapped[UserRole] = mapped_column(
        Enum(UserRole, values_callable=lambda e: [m.value for m in e], native_enum=False, length=20)
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    company: Mapped["Company"] = relationship()
