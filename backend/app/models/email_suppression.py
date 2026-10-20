import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class EmailSuppression(Base):
    """An address outbound mail must skip: it hard-bounced, complained, or
    the provider blocked it (board card A7).

    Platform-wide on purpose: in multi mode every tenant sends from the
    platform identity, so a complaint is a fact about that identity, not
    about one tenant. Holds only SHA-256 of the lowercased address (same
    blind-hash pattern as erasure tombstones), so the list carries no PII,
    needs no erasure hook and can live in every backup. ``company_id``
    records whose mail triggered it, for the trail.
    """

    __tablename__ = "email_suppressions"

    email_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    reason: Mapped[str] = mapped_column(String(20))  # bounce | complaint | blocked | unsubscribe
    source: Mapped[str] = mapped_column(String(20))  # provider name (mailjet)
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    company_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("companies.id", ondelete="SET NULL"), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_event_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
