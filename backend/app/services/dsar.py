"""DSAR export service (Art. 15/20): one read-only bundle per candidate.

Kept admin-mediated on purpose (G0 decision): a leaked status magic link
must never become a full-PII-bundle download, so candidates request via
the status page and the controller fulfills from the panel.
"""

import copy
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import (
    ActivityLog,
    Application,
    ApplicationNote,
    Candidate,
    Company,
    Interview,
)
from app.models.quiz import QuizAttempt
from app.schemas.dsar import (
    DsarActivityEntry,
    DsarAnswer,
    DsarApplication,
    DsarAttempt,
    DsarBundle,
    DsarInterview,
    DsarNote,
)
from app.services import company as company_service
from app.services import storage


def _scrub_integrity(integrity: dict[str, Any] | None) -> dict[str, Any]:
    """Deep-copy minus recruiter identifiers — the reissue/review history is
    the candidate's data (Art. 15), but by_user_id is a third party's."""
    data = copy.deepcopy(integrity or {})
    for section in ("reissue", "review"):
        if isinstance(data.get(section), dict):
            data[section].pop("by_user_id", None)
    return data


def _attempt_out(attempt: QuizAttempt) -> DsarAttempt:
    return DsarAttempt(
        status=attempt.status.value,
        started_at=attempt.started_at,
        completed_at=attempt.completed_at,
        expires_at=attempt.expires_at,
        score=attempt.score,
        per_tag_scores=attempt.per_tag_scores or {},
        integrity=_scrub_integrity(attempt.integrity),
        answers=[
            DsarAnswer(
                question_id=answer.question_id,
                served_at=answer.served_at,
                answered_at=answer.answered_at,
                answer_key=answer.answer_key,
                is_correct=answer.is_correct,
            )
            for answer in sorted(attempt.answers, key=lambda a: a.served_at)
        ],
    )


async def export_candidate(
    db: AsyncSession, company: Company, candidate_id: uuid.UUID
) -> DsarBundle | None:
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
        (
            await db.execute(
                select(Application)
                .where(Application.candidate_id == candidate.id)
                .options(
                    selectinload(Application.job),
                    selectinload(Application.quiz_attempts).selectinload(QuizAttempt.answers),
                )
                .order_by(Application.created_at)
            )
        )
        .scalars()
        .all()
    )
    app_ids = [application.id for application in applications]

    notes: dict[uuid.UUID, list[ApplicationNote]] = {}
    interviews: dict[uuid.UUID, list[Interview]] = {}
    activity_rows: dict[uuid.UUID, list[ActivityLog]] = {}
    if app_ids:
        for note in (
            (
                await db.execute(
                    select(ApplicationNote)
                    .where(ApplicationNote.application_id.in_(app_ids))
                    .order_by(ApplicationNote.created_at)
                )
            )
            .scalars()
            .all()
        ):
            notes.setdefault(note.application_id, []).append(note)
        for interview in (
            (
                await db.execute(
                    select(Interview)
                    .where(Interview.application_id.in_(app_ids))
                    .order_by(Interview.created_at)
                )
            )
            .scalars()
            .all()
        ):
            interviews.setdefault(interview.application_id, []).append(interview)
        for row in (
            (
                await db.execute(
                    select(ActivityLog)
                    .where(ActivityLog.application_id.in_(app_ids))
                    .order_by(ActivityLog.created_at)
                )
            )
            .scalars()
            .all()
        ):
            assert row.application_id is not None  # filtered by the IN clause
            activity_rows.setdefault(row.application_id, []).append(row)

    return DsarBundle(
        generated_at=datetime.now(UTC),
        controller={
            "name": company_service.controller_name(company),
            "privacy_notice_url": company_service.privacy_notice_url(company),
        },
        candidate={
            "name": candidate.name,
            "email": candidate.email,
            "links": candidate.links or {},
            "created_at": candidate.created_at,
        },
        applications=[
            DsarApplication(
                job_title=application.job.title,
                stage=application.stage.value,
                source=application.source,
                message=application.message,
                cv_filename=application.cv_filename,
                cv_size=application.cv_size,
                applied_at=application.created_at,
                cv_download_url=(
                    storage.presign_cv_download(application.cv_object_key, application.cv_filename)
                    if application.cv_object_key
                    else None
                ),
                quiz_attempts=[_attempt_out(a) for a in application.quiz_attempts],
                interviews=[
                    DsarInterview(
                        title=interview.title,
                        timezone=interview.timezone,
                        scheduled_start=interview.scheduled_start,
                        status=interview.status.value,
                        created_at=interview.created_at,
                    )
                    for interview in interviews.get(application.id, [])
                ],
                notes=[
                    DsarNote(body=note.body, created_at=note.created_at)
                    for note in notes.get(application.id, [])
                ],
                activity=[
                    DsarActivityEntry(type=row.type, created_at=row.created_at)
                    for row in activity_rows.get(application.id, [])
                ],
            )
            for application in applications
        ],
    )
