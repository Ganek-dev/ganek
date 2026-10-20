"""Per-tenant abuse guards (STRATEGY_REVIEW §8 "Abuse & quotas").

Three counters per company: emails queued today, application attempts
this hour, jobs published right now. The first two are Redis fixed
windows with the rate limiter's in-process fallback (a Redis outage
degrades to per-process counting instead of taking the apply flow down);
active jobs is a DB count. Limits are read from settings per call so
operators can tune them live; 0 switches a guard off.

Public endpoints answer 429 (volume) or 409 (active jobs). Admins see the
counters on GET /company/usage and a banner from WARN_AT of a limit. One
activity entry per tenant, scope and day records a breach, not one per
hit. Billing enforcement (B1) and CAPTCHA (A5) are deliberately not here.
"""

import time
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import ratelimit
from app.core.config import settings
from app.models import Company, Job, JobStatus
from app.services import activity

EMAILS = "emails"
APPLICATIONS = "applications"
_WINDOW_SECONDS = {EMAILS: 86_400, APPLICATIONS: 3_600}
WARN_AT = 0.8


class QuotaExceeded(Exception):
    def __init__(self, scope: str, limit: int, retry_after: int) -> None:
        super().__init__(f"{scope} quota of {limit} exceeded")
        self.scope = scope
        self.limit = limit
        self.retry_after = retry_after


def limit_for(scope: str) -> int:
    if scope == EMAILS:
        return settings.quota_emails_per_day
    return settings.quota_applications_per_hour


def _window(scope: str, now: float) -> tuple[int, int]:
    seconds = _WINDOW_SECONDS[scope]
    return int(now // seconds), seconds


def _key(company: Company, scope: str, window: int) -> str:
    return f"quota:{company.id}:{scope}:{window}"


async def count(company: Company, scope: str) -> int:
    """Increment and return the current window count. Bookkeeping only:
    callers that enforce use guard()."""
    window, seconds = _window(scope, time.time())
    return await ratelimit.hit_window(_key(company, scope, window), seconds, window)


async def current(company: Company, scope: str) -> int:
    window, _ = _window(scope, time.time())
    return await ratelimit.peek_window(_key(company, scope, window), window)


def _retry_after(scope: str) -> int:
    now = time.time()
    window, seconds = _window(scope, now)
    return max(1, int((window + 1) * seconds - now))


async def _record_breach_once(db: AsyncSession, company: Company, scope: str, limit: int) -> None:
    """One activity entry per tenant, scope and day, not per hit."""
    day = int(time.time() // 86_400)
    flag = f"quota:{company.id}:{scope}:logged:{day}"
    if await ratelimit.hit_window(flag, 86_400, day) != 1:
        return
    activity.record(
        db,
        company_id=company.id,
        type=activity.QUOTA_EXCEEDED,
        payload={"scope": scope, "limit": limit},
    )
    await db.commit()


async def guard(db: AsyncSession, company: Company, scope: str, *, consume: bool) -> None:
    """Raise QuotaExceeded at the limit. ``consume=True`` counts this call
    (applications: every attempt counts, successful or not); ``False`` is a
    read-only pre-check for scopes counted elsewhere (emails are counted
    where they are queued, so admin-triggered mail shows in the same
    number without ever being blocked here)."""
    limit = limit_for(scope)
    if limit <= 0:
        return
    if consume:
        exceeded = await count(company, scope) > limit
    else:
        exceeded = await current(company, scope) >= limit
    if exceeded:
        await _record_breach_once(db, company, scope, limit)
        raise QuotaExceeded(scope, limit, _retry_after(scope))


async def active_jobs(db: AsyncSession, company: Company) -> int:
    result = await db.execute(
        select(func.count())
        .select_from(Job)
        .where(Job.company_id == company.id, Job.status == JobStatus.PUBLISHED)
    )
    return int(result.scalar_one())


async def usage(db: AsyncSession, company: Company) -> dict[str, Any]:
    """Counters plus human warnings for the admin banner (>= WARN_AT)."""
    emails = await current(company, EMAILS)
    applications = await current(company, APPLICATIONS)
    jobs = await active_jobs(db, company)
    rows = (
        (emails, settings.quota_emails_per_day, "emails today"),
        (applications, settings.quota_applications_per_hour, "applications this hour"),
        (jobs, settings.quota_active_jobs, "active jobs"),
    )
    warnings = [
        f"{used} of {limit} {label}"
        for used, limit, label in rows
        if limit > 0 and used >= limit * WARN_AT
    ]
    return {
        "emails_today": emails,
        "emails_per_day_limit": settings.quota_emails_per_day,
        "applications_this_hour": applications,
        "applications_per_hour_limit": settings.quota_applications_per_hour,
        "active_jobs": jobs,
        "active_jobs_limit": settings.quota_active_jobs,
        "warnings": warnings,
    }
