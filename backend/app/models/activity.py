import uuid
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, Index, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.user import User


class ActivityLog(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Append-only feed of tenant events (dashboard 06; Slack webhooks later).

    Rows are written inside the transaction that caused them — a rolled-back
    action leaves no trace. actor is NULL for candidate-initiated events.
    """

    __tablename__ = "activity_log"
    __table_args__ = (Index("ix_activity_log_company_created", "company_id", "created_at"),)

    company_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), index=True
    )
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    application_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("applications.id", ondelete="CASCADE")
    )
    type: Mapped[str] = mapped_column(String(50))
    payload: Mapped[dict[str, object]] = mapped_column(JSONB, default=dict)

    actor: Mapped["User | None"] = relationship(lazy="selectin")

    @property
    def actor_email(self) -> str | None:
        return self.actor.email if self.actor is not None else None
