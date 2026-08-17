"""Nightly retention purge (M5.6 G3) — Art. 5(1)(e) storage limitation,
ON by default (Art. 25): the company can raise `settings.retention_months`
(1–24, default 6) but not silently disable deletion.

Semantics:
- Eligibility is per APPLICATION: stage rejected/withdrawn AND
  `decided_at` older than the company window. `hired` is excluded —
  that record transitions to employee context, out of ATS scope.
- Months are counted as 31 days so the purge never fires EARLIER than
  the privacy notice's "kept for N months" promise.
- Each application goes through the G2 erasure primitive (S3 fail-closed,
  Google best-effort); a storage failure skips just that application —
  it is retried the next night.
- Candidates keep existing while they still have any application; the
  orphan delete afterwards is what finally removes the person.
- One PII-free `retention.purged` receipt per company per run (counts
  only), only when something was actually removed.
- Sweeps: expired `user_invites`; unreferenced `cvs/**` objects older
  than 24 h (upload-then-abandon on the apply form); DONE privacy-request
  tasks 90 days after completion (the note names the candidate on purpose;
  the lasting accountability record is the PII-free activity entry, so the
  task itself only needs to survive the team's own follow-up window).
"""

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, cast

from sqlalchemy import CursorResult, delete, exists, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Application, ApplicationStage, Candidate, Company, Task, UserInvite
from app.services import activity, erasure, storage
from app.services.company import RETENTION_DEFAULT_MONTHS

logger = logging.getLogger(__name__)

DAYS_PER_MONTH = 31  # never purge earlier than the notice's promise
UPLOAD_GRACE = timedelta(hours=24)  # upload-first apply flow needs breathing room
DONE_PRIVACY_TASK_RETENTION = timedelta(days=90)  # completed request tasks name people
PURGEABLE_STAGES = (ApplicationStage.REJECTED, ApplicationStage.WITHDRAWN)


@dataclass
class PurgeSummary:
    applications: int
    candidates: int
    invites: int
    cv_objects: int
    privacy_tasks: int
    google_event_failures: int

    def __str__(self) -> str:  # worker log line
        return (
            f"applications={self.applications} candidates={self.candidates} "
            f"invites={self.invites} cv_objects={self.cv_objects} "
            f"privacy_tasks={self.privacy_tasks} "
            f"google_event_failures={self.google_event_failures}"
        )


async def purge_company(
    db: AsyncSession, company: Company, *, now: datetime
) -> tuple[int, int, int]:
    """Purge one tenant. Returns (applications, candidates, google_failures).

    Commits its own transaction so one company's outcome never entangles
    another's.
    """
    months = (company.settings or {}).get("retention_months") or RETENTION_DEFAULT_MONTHS
    cutoff = now - timedelta(days=DAYS_PER_MONTH * int(months))
    expired = list(
        (
            await db.execute(
                select(Application).where(
                    Application.company_id == company.id,
                    Application.stage.in_(PURGEABLE_STAGES),
                    Application.decided_at.is_not(None),
                    Application.decided_at < cutoff,
                )
            )
        )
        .scalars()
        .all()
    )
    purged = 0
    google_failures = 0
    for application in expired:
        try:
            _, failures = await erasure.erase_application(db, application)
        except Exception:  # noqa: BLE001 - storage down etc.: retry next night
            logger.warning(
                "retention: skipping application %s (storage cleanup failed)", application.id
            )
            continue
        purged += 1
        google_failures += failures

    # RETURNING keeps the not-exists predicate atomic with the delete AND
    # tells us exactly whose privacy-request tasks to scrub afterwards
    removed_emails = list(
        (
            await db.execute(
                delete(Candidate)
                .where(
                    Candidate.company_id == company.id,
                    ~exists(select(Application.id).where(Application.candidate_id == Candidate.id)),
                )
                .returning(Candidate.email)
            )
        )
        .scalars()
        .all()
    )
    for email in removed_emails:
        await erasure.scrub_privacy_request_tasks(db, company.id, email)
    removed_candidates = len(removed_emails)

    if purged or removed_candidates:
        activity.record(
            db,
            company_id=company.id,
            type=activity.RETENTION_PURGED,
            actor_user_id=None,
            application_id=None,
            payload={"applications": purged, "candidates": removed_candidates},
        )
    await db.commit()
    return purged, removed_candidates, google_failures


async def run_purge(db: AsyncSession, *, now: datetime) -> PurgeSummary:
    total_apps = 0
    total_candidates = 0
    total_google_failures = 0
    # only visit tenants with potential work — candidate purges (terminal apps
    # with a ticking clock) or orphaned candidate rows — so the nightly run is
    # O(actual work), not O(all companies ever created
    with_terminal = select(Application.company_id).where(
        Application.stage.in_(PURGEABLE_STAGES), Application.decided_at.is_not(None)
    )
    with_orphans = select(Candidate.company_id).where(
        ~exists(select(Application.id).where(Application.candidate_id == Candidate.id))
    )
    companies = list(
        (
            await db.execute(
                select(Company).where(Company.id.in_(with_terminal) | Company.id.in_(with_orphans))
            )
        )
        .scalars()
        .all()
    )
    for company in companies:
        try:
            apps, candidates, google_failures = await purge_company(db, company, now=now)
        except Exception:  # noqa: BLE001 - one tenant must never block the rest
            logger.exception("retention: purge failed for company %s", company.id)
            await db.rollback()
            continue
        total_apps += apps
        total_candidates += candidates
        total_google_failures += google_failures

    swept_invites = (
        cast(
            "CursorResult[Any]",
            await db.execute(delete(UserInvite).where(UserInvite.expires_at < now)),
        ).rowcount
        or 0
    )
    swept_tasks = (
        cast(
            "CursorResult[Any]",
            await db.execute(
                delete(Task).where(
                    Task.created_by.is_(None),
                    Task.title.like(erasure.PRIVACY_TASK_TITLE_LIKE),
                    Task.done_at.is_not(None),
                    Task.done_at < now - DONE_PRIVACY_TASK_RETENTION,
                )
            ),
        ).rowcount
        or 0
    )
    await db.commit()

    referenced = set(
        (
            await db.execute(
                select(Application.cv_object_key).where(Application.cv_object_key.is_not(None))
            )
        )
        .scalars()
        .all()
    )
    orphan_keys = [
        key
        for key, last_modified in await storage.list_cv_objects()
        if key not in referenced and last_modified < now - UPLOAD_GRACE
    ]
    swept_objects = 0
    if orphan_keys:
        try:
            swept_objects = await storage.delete_objects(orphan_keys)
        except Exception:  # noqa: BLE001 - best-effort; the next run retries
            logger.warning("retention: orphan sweep failed (%d keys)", len(orphan_keys))

    return PurgeSummary(
        applications=total_apps,
        candidates=total_candidates,
        invites=swept_invites,
        cv_objects=swept_objects,
        privacy_tasks=swept_tasks,
        google_event_failures=total_google_failures,
    )
