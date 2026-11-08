"""Plan policy seam (card B1a): the one place the core asks what a company's
plan allows. The core ships ``SelfHostedPolicy`` (no limits, no billing).
A hosted instance swaps in the commercial policy from ``ee/`` through the
``ganek.plan_policy`` entry point, and only when GANEK_EDITION=hosted is set
explicitly: installing the package alone changes nothing, and the AGPL core
has no hidden switch (ee/README.md).
"""

import logging
from dataclasses import dataclass
from functools import lru_cache
from importlib.metadata import entry_points
from typing import Protocol

from app.core.config import settings
from app.models.company import Company

logger = logging.getLogger(__name__)

ENTRY_POINT_GROUP = "ganek.plan_policy"


@dataclass(frozen=True)
class PlanLimits:
    max_live_jobs: int | None  # None = unlimited


UNLIMITED = PlanLimits(max_live_jobs=None)


class PlanPolicy(Protocol):
    name: str
    billing_enabled: bool

    def limits(self, company: Company) -> PlanLimits: ...

    def can_publish(self, company: Company, live_jobs: int) -> bool:
        """``live_jobs`` = the company's published jobs before this publish."""
        ...

    def upgrade_url(self, company: Company) -> str | None: ...


class SelfHostedPolicy:
    """Self-hosters are never metered (BUSINESS_MODEL_PLAN)."""

    name = "self_hosted"
    billing_enabled = False

    def limits(self, company: Company) -> PlanLimits:
        return UNLIMITED

    def can_publish(self, company: Company, live_jobs: int) -> bool:
        return True

    def upgrade_url(self, company: Company) -> str | None:
        return None


def load_plan_policy(edition: str) -> PlanPolicy:
    if edition != "hosted":
        return SelfHostedPolicy()
    found = list(entry_points(group=ENTRY_POINT_GROUP))
    if not found:
        logger.warning(
            "GANEK_EDITION=hosted but no %s entry point is installed (ee/ package "
            "missing); running without plan limits",
            ENTRY_POINT_GROUP,
        )
        return SelfHostedPolicy()
    if len(found) > 1:
        names = ", ".join(sorted(ep.value for ep in found))
        raise RuntimeError(f"more than one {ENTRY_POINT_GROUP} entry point installed: {names}")
    policy: PlanPolicy = found[0].load()()
    logger.info("plan policy: %s", policy.name)
    return policy


@lru_cache(maxsize=1)
def get_plan_policy() -> PlanPolicy:
    return load_plan_policy(settings.edition)
