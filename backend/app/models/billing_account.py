import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class BillingAccount(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One row per hosted company that has touched billing (0050, card B1).
    Written only by the ee/ package; the core never reads Stripe state from
    here, it asks the PlanPolicy. Stripe stays the source of truth: this is
    the minimum enforcement needs, not a subscription mirror."""

    __tablename__ = "billing_accounts"

    company_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), unique=True
    )
    stripe_customer_id: Mapped[str | None] = mapped_column(String(64), unique=True)
    stripe_subscription_id: Mapped[str | None] = mapped_column(String(64))
    # Stripe subscription status as last synced (active, trialing, past_due, ...)
    status: Mapped[str | None] = mapped_column(String(20))
    trial_ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    current_period_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
