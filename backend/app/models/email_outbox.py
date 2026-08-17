import enum
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class EmailStatus(enum.StrEnum):
    QUEUED = "queued"
    SENT = "sent"
    FAILED = "failed"


class EmailOutbox(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One queued/sent/failed outbound email (M5.7 H4 — kills the
    fire-and-forget failure mode of the core loop).

    The row is written in the request that decided to email someone; an arq
    job delivers it with retry. `payload` holds the sender's kwargs verbatim
    (datetimes ISO-wrapped) — it contains recipient PII and capability URLs
    on purpose, which is why rows cascade away with their application and
    terminal rows are swept by the nightly retention job.
    """

    __tablename__ = "email_outbox"

    company_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), index=True
    )
    # candidate-facing mail links its application so the panel can show
    # delivery state AND so erasure takes the stored recipient/URLs with it
    application_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("applications.id", ondelete="CASCADE"), nullable=True, index=True
    )
    kind: Mapped[str] = mapped_column(String(40))  # sender registry key
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    status: Mapped[EmailStatus] = mapped_column(
        Enum(
            EmailStatus,
            values_callable=lambda e: [m.value for m in e],
            native_enum=False,
            length=10,
        ),
        default=EmailStatus.QUEUED,
    )
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
