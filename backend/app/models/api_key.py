import enum
import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Enum, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.company import Company


class ApiKeyScope(enum.StrEnum):
    READ = "read"  # list/read applications, exports
    WRITE = "write"  # read plus the stage PATCH


class ApiKey(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Per-company bearer credential (card D4). The secret is shown once at
    creation and stored only as a sha256 hash (high-entropy random token,
    so no slow hash needed); ``prefix`` is the visible handle. Revocation
    is a timestamp, never a delete, so the activity trail keeps its name."""

    __tablename__ = "api_keys"

    company_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(100))
    prefix: Mapped[str] = mapped_column(String(12))
    key_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    scope: Mapped[ApiKeyScope] = mapped_column(
        Enum(
            ApiKeyScope,
            values_callable=lambda e: [m.value for m in e],
            native_enum=False,
            length=10,
        ),
        default=ApiKeyScope.READ,
    )
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    company: Mapped["Company"] = relationship()
