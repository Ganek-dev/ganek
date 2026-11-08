"""Plan policy seam (card B1a): the one place the core asks what a company's
plan allows. The core ships ``SelfHostedPolicy`` (no limits, no billing).
A hosted instance swaps in the commercial policy from ``ee/`` through the
``ganek.plan_policy`` entry point, and only when GANEK_EDITION=hosted is set
explicitly: installing the package alone changes nothing, and the AGPL core
has no hidden switch (ee/README.md).
"""

import enum
import logging
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from functools import lru_cache
from importlib.metadata import entry_points
from typing import Protocol

from fastapi import APIRouter

from app.core.config import settings
from app.models.company import Company, CompanyPlan

logger = logging.getLogger(__name__)

ENTRY_POINT_GROUP = "ganek.plan_policy"


@dataclass(frozen=True)
class PlanLimits:
    max_live_jobs: int | None  # None = unlimited


UNLIMITED = PlanLimits(max_live_jobs=None)


class PoweredBy(enum.StrEnum):
    """The Ganek attribution on public careers and job pages (card BM10).
    badge = the linked "Powered by Ganek" badge, required on hosted Free;
    credit = the plain unlinked footer line (self-host, optional by BM10);
    none = nothing (paid hosted plans)."""

    BADGE = "badge"
    CREDIT = "credit"
    NONE = "none"


class PlanPolicy(Protocol):
    name: str
    billing_enabled: bool
    # the plan a new signup starts on (Q15: hosted = free, self-hosted stays)
    signup_plan: CompanyPlan

    def limits(self, company: Company) -> PlanLimits: ...

    def can_publish(self, company: Company, live_jobs: int) -> bool:
        """``live_jobs`` = the company's published jobs before this publish."""
        ...

    def upgrade_url(self, company: Company) -> str | None: ...

    def trial_ends_at(self, company: Company) -> datetime | None:
        """When the company's running trial ends (card B1d); None = no trial
        running. ``limits`` and ``can_publish`` already count the trial."""
        ...

    def routers(self) -> Sequence[APIRouter]:
        """Extra API routers the policy mounts under /api/v1 (Q6: the ee/
        billing routes arrive through the same entry point)."""
        ...

    def powered_by(self, company: Company) -> PoweredBy:
        """The attribution the company's public pages carry (BM10)."""
        ...

    def custom_domains(self, company: Company) -> bool:
        """Whether the company may claim a custom careers domain (BM3:
        hosted Team; self-hosters already serve on their own domain)."""
        ...


class SelfHostedPolicy:
    """Self-hosters are never metered (BUSINESS_MODEL_PLAN)."""

    name = "self_hosted"
    billing_enabled = False
    signup_plan = CompanyPlan.SELF_HOSTED

    def limits(self, company: Company) -> PlanLimits:
        return UNLIMITED

    def can_publish(self, company: Company, live_jobs: int) -> bool:
        return True

    def upgrade_url(self, company: Company) -> str | None:
        return None

    def trial_ends_at(self, company: Company) -> datetime | None:
        return None

    def routers(self) -> Sequence[APIRouter]:
        return ()

    def powered_by(self, company: Company) -> PoweredBy:
        # BM10: self-host never has a required badge; the plain credit stays
        return PoweredBy.CREDIT

    def custom_domains(self, company: Company) -> bool:
        # the instance already runs on the operator's own domain
        return False


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


class PlanLimitExceeded(Exception):
    """Publishing would take the company past its plan's live job limit
    (card B1b). The API answers 402 with ``upgrade_url``; it is checked
    before the A4 abuse quota, which keeps its own 409."""

    def __init__(self, limit: int, upgrade_url: str | None) -> None:
        super().__init__(f"plan allows {limit} live jobs")
        self.limit = limit
        self.upgrade_url = upgrade_url

    def detail(self) -> dict[str, object]:
        jobs = "job" if self.limit == 1 else "jobs"
        return {
            "code": "plan_limit",
            "limit": self.limit,
            "upgrade_url": self.upgrade_url,
            "message": (
                f"Your plan allows {self.limit} live {jobs}. "
                "Close a job or upgrade the plan to publish another."
            ),
        }


def ensure_can_publish(policy: PlanPolicy, company: Company, live_jobs: int) -> None:
    """``live_jobs`` = published jobs before this publish. Also covers
    reopening a closed job, which is the same publish transition."""
    if policy.can_publish(company, live_jobs):
        return
    limit = policy.limits(company).max_live_jobs
    raise PlanLimitExceeded(limit if limit is not None else live_jobs, policy.upgrade_url(company))


@lru_cache(maxsize=1)
def get_plan_policy() -> PlanPolicy:
    return load_plan_policy(settings.edition)
