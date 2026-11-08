import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.company import CompanyPlan


class BillingAccount(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One row per hosted company that has touched billing (0050, card B1).
    Written by the ee/ package, except ``plan_override`` and ending a
    running trial, which the operator plane (services/ops.py) writes; the
    core never reads Stripe state from here, it asks the PlanPolicy. Stripe
    stays the source of truth: this is the minimum enforcement needs, not a
    subscription mirror."""

    __tablename__ = "billing_accounts"

    company_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), unique=True
    )
    stripe_customer_id: Mapped[str | None] = mapped_column(String(64), unique=True)
    stripe_subscription_id: Mapped[str | None] = mapped_column(String(64))
    # Stripe subscription status as last synced (active, trialing, past_due, ...)
    status: Mapped[str | None] = mapped_column(String(20))
    # our own 14-day Team trial without a card (card B1d, Q9), not Stripe's:
    # set once by the admin's start, never cleared, so a second start is
    # refused; the trial is over when it lies in the past
    trial_ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    current_period_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # operator-set plan (0051, Q21): when set it is the effective plan, over
    # companies.plan and any trial. Only a superadmin sets or clears it
    # (/ops); the Stripe webhook never writes it, so a replay keeps it.
    plan_override: Mapped[CompanyPlan | None] = mapped_column(
        Enum(
            CompanyPlan,
            values_callable=lambda e: [m.value for m in e],
            native_enum=False,
            length=12,
        )
    )
