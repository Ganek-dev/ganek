import uuid
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.api_key import ApiKey
    from app.models.application import Application
    from app.models.user import User


class AccessLog(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Who looked at which candidate (read-access audit trail).

    Separate from activity_log on purpose: reads are frequent and would
    bury the feed. One of actor_user_id / api_key_id is set. Rows cascade
    with the application (erasure, retention purge) like notes do.
    """

    __tablename__ = "access_log"
    __table_args__ = (
        Index("ix_access_log_application_created", "application_id", "created_at"),
        Index("ix_access_log_company_created", "company_id", "created_at"),
    )

    company_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), index=True
    )
    application_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("applications.id", ondelete="CASCADE")
    )
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    api_key_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("api_keys.id", ondelete="SET NULL")
    )
    action: Mapped[str] = mapped_column(String(30))

    actor: Mapped["User | None"] = relationship(lazy="selectin")
    api_key: Mapped["ApiKey | None"] = relationship(lazy="selectin")
    # loaded explicitly by the company-wide listing (candidate name, job title)
    application: Mapped["Application"] = relationship()

    @property
    def actor_email(self) -> str | None:
        return self.actor.email if self.actor is not None else None

    @property
    def actor_label(self) -> str | None:
        return self.actor.display_label if self.actor is not None else None

    @property
    def api_key_name(self) -> str | None:
        return self.api_key.name if self.api_key is not None else None
