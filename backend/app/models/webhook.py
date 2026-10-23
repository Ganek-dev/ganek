import enum
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class DeliveryStatus(enum.StrEnum):
    QUEUED = "queued"
    DELIVERED = "delivered"
    FAILED = "failed"  # parked after MAX_ATTEMPTS; visible on the Developers page


class WebhookEndpoint(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """An admin-registered HTTPS URL subscribed to tenant events (card D4
    part B). The signing secret is shown once and kept Fernet-encrypted
    like Google refresh tokens: the worker needs it back to sign."""

    __tablename__ = "webhook_endpoints"

    company_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(100))
    url: Mapped[str] = mapped_column(String(500))
    secret_enc: Mapped[str] = mapped_column(Text)
    events: Mapped[list[str]] = mapped_column(JSONB, default=list)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )


class WebhookDelivery(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One event for one endpoint. Written in the request that caused the
    event (after its commit), delivered by the worker with retries; the
    row IS the delivery log the Developers page shows."""

    __tablename__ = "webhook_deliveries"
    __table_args__ = (
        Index("ix_webhook_deliveries_endpoint_created", "endpoint_id", "created_at"),
        Index("ix_webhook_deliveries_status_created", "status", "created_at"),
    )

    company_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), index=True
    )
    endpoint_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("webhook_endpoints.id", ondelete="CASCADE")
    )
    event: Mapped[str] = mapped_column(String(40))
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    status: Mapped[DeliveryStatus] = mapped_column(
        Enum(
            DeliveryStatus,
            values_callable=lambda e: [m.value for m in e],
            native_enum=False,
            length=10,
        ),
        default=DeliveryStatus.QUEUED,
    )
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    response_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
