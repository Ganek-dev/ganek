"""Candidate erasure (GDPR Art. 17). One service, several triggers - the
admin action, the G3 retention purge, a candidate request flow later.

Ordering is deliberate, per application:
1. S3 CV object first, fail-closed - a storage error aborts before any row
   disappears, because ``applications.cv_object_key`` is the only pointer to
   the object and the row cascade would strand it forever.
2. A Core ``DELETE`` so the Postgres cascades take the child rows
   (an ORM delete would try to NULL NOT NULL FKs).
3. For a booked future interview the interviewer gets a METHOD:CANCEL
   notice without any candidate data, queued by the caller AFTER its
   commit (``queue_cancel_notices``), so the event leaves their calendar.

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
from datetime import UTC, datetime
from typing import Any, cast

from sqlalchemy import CursorResult, delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Application, Candidate, Company, Interview, InterviewStatus, Job, Task
from app.services import activity, ics, storage, tombstones
from app.services import outbox as outbox_service

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
    cancel_notices: int
    tasks: int


@dataclass(frozen=True)
class CancelNotice:
    """What the interviewer's METHOD:CANCEL mail needs once the application
    row is gone. No candidate name or email on purpose."""

    company_id: uuid.UUID
    company_name: str
    interviewer_email: str
    interviewer_name: str
    job_title: str
    title: str
    start: datetime
    duration_minutes: int
    timezone: str
    location: str
    uid: str
    sequence: int


async def queue_cancel_notices(db: AsyncSession, notices: list[CancelNotice]) -> int:
    """Queue the interviewer notices collected by ``erase_application``.
    Call AFTER the caller's commit: ``outbox.queue_email`` commits. Returns
    how many were queued; a failure is logged and never fails the erase
    that already happened (a retry would only 404 on the gone rows)."""
    queued = 0
    for notice in notices:
        try:
            await queue_one_cancel_notice(db, notice)
        except Exception:  # noqa: BLE001 - the erase succeeded; the notice is best-effort
            logger.warning(
                "erasure: could not queue the interviewer cancel notice for %s (uid %s)",
                notice.interviewer_email,
                notice.uid,
                exc_info=True,
            )
            await db.rollback()
            continue
        queued += 1
    return queued


async def queue_one_cancel_notice(db: AsyncSession, notice: CancelNotice) -> None:
    await outbox_service.queue_email(
        db,
        kind="interview_cancelled_interviewer",
        company_id=notice.company_id,
        application_id=None,
        to=notice.interviewer_email,
        ref=None,
        candidate_name="",
        candidate_email="",
        interviewer_name=notice.interviewer_name,
        job_title=notice.job_title,
        company_name=notice.company_name,
        title=notice.title,
        start=notice.start,
        duration_minutes=notice.duration_minutes,
        timezone=notice.timezone,
        location=notice.location,
        uid=notice.uid,
        sequence=notice.sequence,
        cancelled_by="The application was deleted",
    )


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


async def erase_application(db: AsyncSession, application: Application) -> list[CancelNotice]:
    """Delete one application and everything hanging off it. Returns the
    cancel notices owed to interviewers (booked interviews in the future),
    which the caller queues after committing.

    No commit here - the admin erase and the retention purge own the
    transaction and the bookkeeping.
    """
    if application.cv_object_key:
        await storage.delete_object(application.cv_object_key)

    notices: list[CancelNotice] = []
    booked = list(
        (
            await db.execute(
                select(Interview).where(
                    Interview.application_id == application.id,
                    Interview.status == InterviewStatus.BOOKED,
                    Interview.scheduled_start > datetime.now(UTC),
                )
            )
        )
        .scalars()
        .all()
    )
    if booked:
        company_name = (
            await db.execute(select(Company.name).where(Company.id == application.company_id))
        ).scalar_one()
        job_title = (
            await db.execute(select(Job.title).where(Job.id == application.job_id))
        ).scalar_one()
        for interview in booked:
            assert interview.scheduled_start is not None  # filtered above
            notices.append(
                CancelNotice(
                    company_id=application.company_id,
                    company_name=company_name,
                    interviewer_email=interview.interviewer.email,
                    interviewer_name=interview.interviewer.display_label,
                    job_title=job_title,
                    title=interview.title,
                    start=interview.scheduled_start,
                    duration_minutes=interview.duration_minutes,
                    timezone=interview.timezone,
                    location=interview.location,
                    uid=ics.interview_uid(interview.id),
                    sequence=interview.ics_sequence + 1,
                )
            )

    # blind marker so a restored backup cannot bring this application back
    await tombstones.record(
        db,
        company_id=application.company_id,
        kind=tombstones.APPLICATION,
        subject_id=application.id,
    )
    await db.execute(delete(Application).where(Application.id == application.id))
    return notices


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
    notices: list[CancelNotice] = []
    for application in applications:
        notices.extend(await erase_application(db, application))

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
    queued = await queue_cancel_notices(db, notices)
    return EraseSummary(
        applications=len(applications),
        cv_objects=cv_objects,
        cancel_notices=queued,
        tasks=scrubbed_tasks,
    )
