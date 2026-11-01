import enum
import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import BigInteger, Boolean, DateTime, Enum, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.company import Company


class UserRole(enum.StrEnum):
    ADMIN = "admin"
    MEMBER = "member"
    REVIEWER = "reviewer"


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
    # bumped on password change / forced logout - embedded in the session
    # token; a mismatch invalidates every session issued before the bump
    token_version: Mapped[int] = mapped_column(Integer, default=0)
    # what teammates and candidates see (card D14); NULL falls back to the
    # email local part via display_label
    display_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    # second factor (card A6): Fernet-encrypted base32 secret, enabled only
    # once confirmed; last accepted step blocks replays; sha256 of unused
    # recovery codes
    totp_secret: Mapped[str | None] = mapped_column(Text, nullable=True)
    totp_enabled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    totp_last_step: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    recovery_codes: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)
    # saved weekly interview availability; NULL = default Mon-Fri 09:00-17:00
    interview_availability: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    # default meeting place for interviews this user runs (room or video
    # link); copied onto each request, editable per request (0040)
    interview_location: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # derived dashboard queue items this user hid (card D13): item keys such
    # as "job-quiz:<job_id>"; services/queue.py prunes keys whose item resolved
    queue_dismissed: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)

    company: Mapped["Company"] = relationship(back_populates="users")

    @property
    def has_password(self) -> bool:
        return self.password_hash is not None

    @property
    def is_anonymized(self) -> bool:
        """The tombstone left by services.users.anonymize_user (same pattern
        as the team-list filter: deleted-%@invalid)."""
        return self.email.startswith("deleted-") and self.email.endswith("@invalid")

    @property
    def display_label(self) -> str:
        """Display name when set, else the email local part made readable
        (jane.doe -> Jane Doe): the one fallback every surface shares.
        An anonymized teammate reads "Former teammate" everywhere."""
        if self.is_anonymized:
            return "Former teammate"
        if self.display_name:
            return self.display_name
        local = self.email.split("@")[0]
        return local.replace(".", " ").replace("_", " ").replace("-", " ").title() or self.email

    @property
    def mfa_enabled(self) -> bool:
        return self.totp_enabled_at is not None and self.totp_secret is not None

    @property
    def recovery_codes_left(self) -> int:
        return len(self.recovery_codes or [])
