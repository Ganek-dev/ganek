"""Candidate erasure (GDPR Art. 17). One service, several triggers - the
admin action, the G3 retention purge, a candidate request flow later.

Ordering is deliberate, per application:
1. S3 CV object first, fail-closed - a storage error aborts before any row
   disappears, because ``applications.cv_object_key`` is the only pointer to
   the object and the row cascade would strand it forever.
2. Google Calendar events best-effort - they live on the recruiter's
   personal calendar; failures are logged and reported, never blocking.
3. A Core ``DELETE`` so the Postgres cascades take the child rows
   (an ORM delete would try to NULL NOT NULL FKs).

``erase_application`` is the per-application primitive (no commit - the
caller owns the transaction); ``erase_candidate`` wraps it for the whole
person, scrubs the system-created privacy-request tasks naming them, and
writes the anonymized ``candidate.erased`` receipt with
``application_id=None`` (the linked rows just cascaded away) and a
count-only payload.
"""

import logging
import uuid
from dataclasses import dataclass
from typing import Any, cast

from sqlalchemy import CursorResult, delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Application, Candidate, Company, Interview, Task
from app.services import activity, storage, tombstones

logger = logging.getLogger(__name__)

# Title shape of the tasks the public request-data/request-deletion endpoints
# create (see api/public.py _record_privacy_request). The scrub below and the
# nightly done-task sweep both match on it; test_erasure pins the coupling by
# creating the task through the real endpoint.
PRIVACY_TASK_TITLE_LIKE = "Privacy: %request - %"


@dataclass
class EraseSummary:
    applications: int
    cv_objects: int
    google_events: int
    google_event_failures: int
    tasks: int


def _like_literal(text: str) -> str:
    """Escape LIKE wildcards so an email like a_b@x.dev matches literally."""
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


async def scrub_privacy_request_tasks(
    db: AsyncSession, company_id: uuid.UUID, candidate_email: str
) -> int:
    """Delete the system-created privacy-request tasks naming a candidate.

    Those tasks carry the candidate's name+email on purpose (the task IS the
    request) - but they must not outlive the person they name. Matching is
    deliberately narrow: system-created only (created_by NULL), the request
    title shape, and the "(email)" the note carries. A task a human typed
    that merely mentions the candidate is the recruiter's own record and
    stays (the self-hosting guide tells them to check those by hand).
    """
    result = cast(
        "CursorResult[Any]",
        await db.execute(
            delete(Task).where(
                Task.company_id == company_id,
                Task.created_by.is_(None),
                Task.title.like(PRIVACY_TASK_TITLE_LIKE),
                Task.note.like(f"%({_like_literal(candidate_email)})%", escape="\\"),
            )
        ),
    )
    return result.rowcount or 0


async def erase_application(db: AsyncSession, application: Application) -> tuple[int, int]:
    """Erase ONE application: S3 fail-closed, Google best-effort, row delete.

    Returns (google_events_attempted, google_events_failed). No commit, no
    receipt - callers (admin erase, retention purge) own transaction and
    bookkeeping.
    """
    if application.cv_object_key:
        await storage.delete_object(application.cv_object_key)

    # Task 9 of the ICS-only plan replaces the Google event deletion with a
    # cancel notice to the interviewer; until then nothing to do here.
    interviews: list[Interview] = []
    failures = 0

    # blind marker so a restored backup cannot bring this application back
    await tombstones.record(
        db,
        company_id=application.company_id,
        kind=tombstones.APPLICATION,
        subject_id=application.id,
    )
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

    scrubbed_tasks = await scrub_privacy_request_tasks(db, company.id, candidate.email)
    await tombstones.record(
        db, company_id=company.id, kind=tombstones.CANDIDATE, subject_id=candidate.id
    )
    await db.execute(delete(Candidate).where(Candidate.id == candidate.id))
    activity.record(
        db,
        company_id=company.id,
        type=activity.CANDIDATE_ERASED,
        actor_user_id=actor_user_id,
        application_id=None,
        payload={"applications": len(applications), "tasks": scrubbed_tasks},
    )
    await db.commit()
    return EraseSummary(
        applications=len(applications),
        cv_objects=cv_objects,
        google_events=attempted - failed,
        google_event_failures=failed,
        tasks=scrubbed_tasks,
    )
