import uuid
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, ForeignKey, Index, String, Text, false, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.company import Company


class EmailTemplate(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A workspace's own subject and body for one candidate stage mail kind
    (card "Candidate emails", PR 3). The built-in template stays in code
    (``email_render.BUILTIN``) and is the fallback when no row is the
    default; the outbox snapshots the resolved text at queue time, so a
    later edit or delete never changes an in-flight mail."""

    __tablename__ = "email_templates"
    __table_args__ = (
        Index(
            "ix_email_templates_default_per_kind",
            "company_id",
            "kind",
            unique=True,
            postgresql_where=text("is_default"),
        ),
    )

    company_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[str] = mapped_column(String(40))
    name: Mapped[str] = mapped_column(String(80))
    subject: Mapped[str] = mapped_column(String(200))
    body: Mapped[str] = mapped_column(Text)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    company: Mapped["Company"] = relationship()
