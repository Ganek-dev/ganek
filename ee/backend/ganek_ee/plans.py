"""Hosted plan policy, loaded by the core through the ganek.plan_policy entry
point when GANEK_EDITION=hosted (app/core/plans.py).

B1b adds the BM3 live job limits per ``companies.plan``. B1c adds Stripe:
billing is on only when every Stripe variable is set (ganek_ee.billing.
config); then the 402 links to the in-app billing page and the billing
routes mount. B1d adds the 14-day Team trial without a card: it lives in
``billing_accounts.trial_ends_at`` (Q9), a Free company counts as Team
while it runs and is Free again after it (B1b over-limit rule, Q8).
The operator plan override (``billing_accounts.plan_override``, Q21) wins
over both: set by a superadmin, never by the webhook.
"""

import os
from collections.abc import Sequence
from datetime import UTC, datetime

from fastapi import APIRouter
from sqlalchemy import inspect

from app.core import urls
from app.core.plans import UNLIMITED, PlanLimits, PoweredBy
from app.models import BillingAccount
from app.models.company import Company, CompanyPlan
from ganek_ee.billing.config import stripe_config_from_env

# BM3: Free 1, Starter 5, Team unlimited live jobs. self_hosted never
# appears on a hosted tenant after the backfill, but stays unlimited.
LIVE_JOB_LIMITS: dict[CompanyPlan, int | None] = {
    CompanyPlan.FREE: 1,
    CompanyPlan.STARTER: 5,
    CompanyPlan.TEAM: None,
    CompanyPlan.SELF_HOSTED: None,
}

# Where the 402 sends an admin while Stripe is not configured (a pricing or
# contact page), unset = none. With Stripe it is the in-app billing page.
UPGRADE_URL_ENV = "GANEK_UPGRADE_URL"

TRIAL_PLAN = CompanyPlan.TEAM


def now() -> datetime:
    """The policy's clock; tests freeze it here."""
    return datetime.now(UTC)


def _account(company: Company) -> BillingAccount | None:
    """The billing row, only when it came with the company (the relationship
    is eager): an async session must never lazy-load inside the sync policy."""
    if "billing_account" in inspect(company).unloaded:
        return None
    return company.billing_account


def trial_end(company: Company) -> datetime | None:
    """The stored trial end, running or not."""
    account = _account(company)
    return account.trial_ends_at if account is not None else None


def plan_override(company: Company) -> CompanyPlan | None:
    """The operator override (Q21), None = the Stripe-synced plan decides."""
    account = _account(company)
    return account.plan_override if account is not None else None


def effective_plan(company: Company) -> CompanyPlan:
    """The operator override wins over everything. Otherwise a Free company
    on a running trial counts as Team; a paid plan wins over a trial (it is
    already paid for)."""
    override = plan_override(company)
    if override is not None:
        return override
    if company.plan is CompanyPlan.FREE:
        end = trial_end(company)
        if end is not None and end > now():
            return TRIAL_PLAN
    return company.plan


class HostedPolicy:
    name = "hosted"
    signup_plan = CompanyPlan.FREE  # Q15

    def __init__(self) -> None:
        # read once: the core resolves the policy once per process
        self.billing_enabled = stripe_config_from_env() is not None

    def limits(self, company: Company) -> PlanLimits:
        max_live = LIVE_JOB_LIMITS.get(effective_plan(company))
        return UNLIMITED if max_live is None else PlanLimits(max_live_jobs=max_live)

    def can_publish(self, company: Company, live_jobs: int) -> bool:
        max_live = self.limits(company).max_live_jobs
        return max_live is None or live_jobs < max_live

    def upgrade_url(self, company: Company) -> str | None:
        if self.billing_enabled:
            return urls.admin_billing_url(company)
        return os.environ.get(UPGRADE_URL_ENV) or None

    def trial_ends_at(self, company: Company) -> datetime | None:
        # an override decides the plan on its own: no trial is running then
        if company.plan is not CompanyPlan.FREE or plan_override(company) is not None:
            return None
        end = trial_end(company)
        return end if end is not None and end > now() else None

    def routers(self) -> Sequence[APIRouter]:
        if not self.billing_enabled:
            return ()
        from ganek_ee.billing.api import router  # the API layer, only when used

        return (router,)

    def powered_by(self, company: Company) -> PoweredBy:
        """BM10: the badge is required on Free and removed on paid plans.
        A running Team trial counts as Team, so it carries no badge."""
        plan = effective_plan(company)
        if plan is CompanyPlan.FREE:
            return PoweredBy.BADGE
        if plan is CompanyPlan.SELF_HOSTED:
            return PoweredBy.CREDIT
        return PoweredBy.NONE
