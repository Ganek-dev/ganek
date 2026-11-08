"""Hosted plan policy, loaded by the core through the ganek.plan_policy entry
point when GANEK_EDITION=hosted (app/core/plans.py).

B1a ships the seam only: limits arrive with B1b, billing with B1c. Until
then the hosted policy allows everything, exactly like the core default.
"""

from app.core.plans import UNLIMITED, PlanLimits
from app.models.company import Company


class HostedPolicy:
    name = "hosted"
    billing_enabled = False  # flips on with Stripe (card B1c)

    def limits(self, company: Company) -> PlanLimits:
        return UNLIMITED

    def can_publish(self, company: Company, live_jobs: int) -> bool:
        return True

    def upgrade_url(self, company: Company) -> str | None:
        return None
