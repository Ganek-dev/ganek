"""Hosted plan policy, loaded by the core through the ganek.plan_policy entry
point when GANEK_EDITION=hosted (app/core/plans.py).

B1b adds the BM3 live job limits per ``companies.plan``. Billing (Stripe)
arrives with B1c, so ``billing_enabled`` stays false until then.
"""

import os

from app.core.plans import UNLIMITED, PlanLimits
from app.models.company import Company, CompanyPlan

# BM3: Free 1, Starter 5, Team unlimited live jobs. self_hosted never
# appears on a hosted tenant after the backfill, but stays unlimited.
LIVE_JOB_LIMITS: dict[CompanyPlan, int | None] = {
    CompanyPlan.FREE: 1,
    CompanyPlan.STARTER: 5,
    CompanyPlan.TEAM: None,
    CompanyPlan.SELF_HOSTED: None,
}

# Where the 402 sends an admin. B1c points it at the in-app billing page;
# until then the operator sets it (a pricing or contact page), unset = none.
UPGRADE_URL_ENV = "GANEK_UPGRADE_URL"


class HostedPolicy:
    name = "hosted"
    billing_enabled = False  # flips on with Stripe (card B1c)
    signup_plan = CompanyPlan.FREE  # Q15

    def limits(self, company: Company) -> PlanLimits:
        max_live = LIVE_JOB_LIMITS.get(company.plan)
        return UNLIMITED if max_live is None else PlanLimits(max_live_jobs=max_live)

    def can_publish(self, company: Company, live_jobs: int) -> bool:
        max_live = self.limits(company).max_live_jobs
        return max_live is None or live_jobs < max_live

    def upgrade_url(self, company: Company) -> str | None:
        return os.environ.get(UPGRADE_URL_ENV) or None
