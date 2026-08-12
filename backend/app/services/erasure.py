"""Candidate erasure (GDPR Art. 17). One service, several triggers — the
admin action today, the retention purge in G3, a candidate request flow
later.

Ordering is deliberate:
1. S3 CV objects first, fail-closed — a storage error aborts before any row
   disappears, because ``applications.cv_object_key`` is the only pointer to
   the object and the row cascade would strand it forever.
2. Google Calendar events best-effort — they live on the recruiter's
   personal calendar; failures are logged and reported, never blocking.
3. A Core ``DELETE`` on the candidate row so the Postgres cascades take
   applications → attempts → answers → notes → interviews → activity rows
   (an ORM delete would try to NULL the NOT NULL ``candidate_id`` FK).
4. One anonymized ``candidate.erased`` receipt with ``application_id=None``
   (the linked rows just cascaded away) and a count-only payload.
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

    applications = (
        (await db.execute(select(Application).where(Application.candidate_id == candidate.id)))
        .scalars()
        .all()
    )
    app_ids = [application.id for application in applications]
    interviews: list[Interview] = []
    if app_ids:
        interviews = list(
            (
                await db.execute(
                    select(Interview).where(
                        Interview.application_id.in_(app_ids),
                        Interview.google_event_id.is_not(None),
                    )
                )
            )
            .scalars()
            .all()
        )

    cv_keys = [a.cv_object_key for a in applications if a.cv_object_key]
    for key in cv_keys:
        await storage.delete_object(key)

    event_failures = 0
    for interview in interviews:
        try:
            assert interview.google_event_id is not None  # filtered above
            await google_calendar.delete_event(db, interview.interviewer, interview.google_event_id)
        except google_calendar.GoogleCalendarError:
            # covers NeedsReconnectError too (subclass)
            logger.warning("erasure: could not delete google event for interview %s", interview.id)
            event_failures += 1

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
        cv_objects=len(cv_keys),
        google_events=len(interviews) - event_failures,
        google_event_failures=event_failures,
    )
