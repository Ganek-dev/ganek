"""Candidate erasure (GDPR Art. 17). One service, several triggers — the
admin action, the G3 retention purge, a candidate request flow later.

Ordering is deliberate, per application:
1. S3 CV object first, fail-closed — a storage error aborts before any row
   disappears, because ``applications.cv_object_key`` is the only pointer to
   the object and the row cascade would strand it forever.
2. Google Calendar events best-effort — they live on the recruiter's
   personal calendar; failures are logged and reported, never blocking.
3. A Core ``DELETE`` so the Postgres cascades take the child rows
   (an ORM delete would try to NULL NOT NULL FKs).

``erase_application`` is the per-application primitive (no commit — the
caller owns the transaction); ``erase_candidate`` wraps it for the whole
person and writes the anonymized ``candidate.erased`` receipt with
``application_id=None`` (the linked rows just cascaded away) and a
count-only payload.
"""

import logging
import uuid
from dataclasses import dataclass

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Application, Candidate, Company, Interview
from app.services import activity, google_calendar, storage

logger = logging.getLogger(__name__)


@dataclass
class EraseSummary:
    applications: int
    cv_objects: int
    google_events: int
    google_event_failures: int


async def erase_application(db: AsyncSession, application: Application) -> tuple[int, int]:
    """Erase ONE application: S3 fail-closed, Google best-effort, row delete.

    Returns (google_events_attempted, google_events_failed). No commit, no
    receipt — callers (admin erase, retention purge) own transaction and
    bookkeeping.
    """
    if application.cv_object_key:
        await storage.delete_object(application.cv_object_key)

    interviews = list(
        (
            await db.execute(
                select(Interview).where(
                    Interview.application_id == application.id,
                    Interview.google_event_id.is_not(None),
                )
            )
        )
        .scalars()
        .all()
    )
    failures = 0
    for interview in interviews:
        try:
            assert interview.google_event_id is not None  # filtered above
            await google_calendar.delete_event(db, interview.interviewer, interview.google_event_id)
        except google_calendar.GoogleCalendarError:
            # covers NeedsReconnectError too (subclass)
            logger.warning("erasure: could not delete google event for interview %s", interview.id)
            failures += 1

    await db.execute(delete(Application).where(Application.id == application.id))
    return len(interviews), failures


async def erase_candidate(
    db: AsyncSession,
    company: Company,
    candidate_id: uuid.UUID,
    *,
    actor_user_id: uuid.UUID | None,
) -> EraseSummary | None:
    candidate = (
        await db.execute(
            select(Candidate).where(
                Candidate.id == candidate_id, Candidate.company_id == company.id
            )
        )
    ).scalar_one_or_none()
    if candidate is None:
        return None

    applications = list(
        (await db.execute(select(Application).where(Application.candidate_id == candidate.id)))
        .scalars()
        .all()
    )
    cv_objects = sum(1 for a in applications if a.cv_object_key)
    attempted = 0
    failed = 0
    for application in applications:
        events, failures = await erase_application(db, application)
        attempted += events
        failed += failures

    await db.execute(delete(Candidate).where(Candidate.id == candidate.id))
    activity.record(
        db,
        company_id=company.id,
        type=activity.CANDIDATE_ERASED,
        actor_user_id=actor_user_id,
        application_id=None,
        payload={"applications": len(applications)},
    )
    await db.commit()
    return EraseSummary(
        applications=len(applications),
        cv_objects=cv_objects,
        google_events=attempted - failed,
        google_event_failures=failed,
    )
