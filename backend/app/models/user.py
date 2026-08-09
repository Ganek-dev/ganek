import enum
import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.company import Company


class UserRole(enum.StrEnum):
    ADMIN = "admin"
    MEMBER = "member"


class User(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "users"

    company_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), index=True
    )
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    # NULL for Google-only accounts (signed up via Google, no password set)
    password_hash: Mapped[str | None] = mapped_column(String(200), nullable=True)
    # Google's stable OIDC subject; the durable identity key once linked
    google_sub: Mapped[str | None] = mapped_column(
        String(255), unique=True, index=True, nullable=True
    )
    role: Mapped[UserRole] = mapped_column(
        Enum(UserRole, values_callable=lambda e: [m.value for m in e], native_enum=False, length=20)
    )
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    # bumped on password change / forced logout — embedded in the session
    # token; a mismatch invalidates every session issued before the bump
    token_version: Mapped[int] = mapped_column(Integer, default=0)
    # saved weekly interview availability; NULL = default Mon-Fri 09:00-17:00
    interview_availability: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    company: Mapped["Company"] = relationship(back_populates="users")

    @property
    def has_password(self) -> bool:
        return self.password_hash is not None
