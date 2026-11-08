"""Hosted plan policy, loaded by the core through the ganek.plan_policy entry
point when GANEK_EDITION=hosted (app/core/plans.py).

B1b adds the BM3 live job limits per ``companies.plan``. B1c adds Stripe:
billing is on only when every Stripe variable is set (ganek_ee.billing.
config); then the 402 links to the in-app billing page and the billing
routes mount.
"""

import os
from collections.abc import Sequence

from fastapi import APIRouter

from app.core import urls
from app.core.plans import UNLIMITED, PlanLimits
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


class HostedPolicy:
    name = "hosted"
    signup_plan = CompanyPlan.FREE  # Q15

    def __init__(self) -> None:
        # read once: the core resolves the policy once per process
        self.billing_enabled = stripe_config_from_env() is not None

    def limits(self, company: Company) -> PlanLimits:
        max_live = LIVE_JOB_LIMITS.get(company.plan)
        return UNLIMITED if max_live is None else PlanLimits(max_live_jobs=max_live)

    def can_publish(self, company: Company, live_jobs: int) -> bool:
        max_live = self.limits(company).max_live_jobs
        return max_live is None or live_jobs < max_live

    def upgrade_url(self, company: Company) -> str | None:
        if self.billing_enabled:
            return urls.admin_billing_url(company)
        return os.environ.get(UPGRADE_URL_ENV) or None

    def routers(self) -> Sequence[APIRouter]:
        if not self.billing_enabled:
            return ()
        from ganek_ee.billing.api import router  # the API layer, only when used

        return (router,)
