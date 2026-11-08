import enum
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import DateTime, Enum, String, Text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.billing_account import BillingAccount
    from app.models.job import Job
    from app.models.user import User


class CompanyPlan(enum.StrEnum):
    """Billing plan (0050, BM3). self_hosted = no limits; the other three are
    only ever set on a hosted instance and are read through the PlanPolicy
    (app/core/plans.py), never compared ad hoc."""

    FREE = "free"
    STARTER = "starter"
    TEAM = "team"
    SELF_HOSTED = "self_hosted"


class Company(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "companies"

    slug: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    logo_url: Mapped[str | None] = mapped_column(String(500))
    website: Mapped[str | None] = mapped_column(String(500))
    socials: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    theme: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    settings: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    # bank question ids this company never wants served, across all its jobs
    blocked_question_ids: Mapped[list[str]] = mapped_column(ARRAY(String(100)), default=list)
    # default screening questions copied into every new job (0039); shape in
    # services.screening.ScreeningQuestion
    screening_questions: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    # default scorecard criteria copied into every new job (0042)
    scorecard_template: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    # operator suspension (0049, services/ops.py): set = public pages answer
    # 503 and every sign-in, session and API key of the tenant is refused
    suspended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    suspension_reason: Mapped[str | None] = mapped_column(String(500))
    plan: Mapped[CompanyPlan] = mapped_column(
        Enum(
            CompanyPlan,
            values_callable=lambda e: [m.value for m in e],
            native_enum=False,
            length=12,
        ),
        default=CompanyPlan.SELF_HOSTED,
        server_default=CompanyPlan.SELF_HOSTED.value,
    )

    users: Mapped[list["User"]] = relationship(back_populates="company")
    jobs: Mapped[list["Job"]] = relationship(back_populates="company")
    # read side of the ee/ billing row (card B1d): the hosted policy needs
    # the DB-held trial end to work out the effective plan synchronously, so
    # it is loaded with the company (one indexed SELECT, nothing when absent).
    # viewonly: ee/ writes billing_accounts through its own store, the
    # operator plane writes plan_override (services/ops.py).
    billing_account: Mapped["BillingAccount | None"] = relationship(
        lazy="selectin", viewonly=True, uselist=False
    )
