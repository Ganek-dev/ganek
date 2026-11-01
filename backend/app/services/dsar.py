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

from app.core import urls
from app.models import (
    ActivityLog,
    Application,
    ApplicationNote,
    Candidate,
    Company,
    EmailOutbox,
    Interview,
)
from app.models.quiz import QuizAttempt
from app.models.scorecard import Scorecard
from app.schemas.dsar import (
    DsarActivityEntry,
    DsarAnswer,
    DsarApplication,
    DsarAttempt,
    DsarBundle,
    DsarEmail,
    DsarInterview,
    DsarNote,
    DsarScorecard,
)
from app.schemas.public import StatusScreeningAnswer
from app.services import company as company_service
from app.services import rejection_reasons, storage


def _scrub_integrity(integrity: dict[str, Any] | None) -> dict[str, Any]:
    """Deep-copy minus recruiter identifiers - the reissue/review history is
    the candidate's data (Art. 15), but by_user_id is a third party's."""
    data = copy.deepcopy(integrity or {})
    for section in ("reissue", "review"):
        if isinstance(data.get(section), dict):
            data[section].pop("by_user_id", None)
    return data


def _scorecard_out(row: Scorecard) -> DsarScorecard:
    assert row.submitted_at is not None and row.recommendation is not None  # submitted rows
    return DsarScorecard(
        submitted_at=row.submitted_at,
        criteria=[
            {"label": c["label"], "rating": row.ratings.get(str(c["id"]))}
            for c in row.criteria_snapshot
        ],
        recommendation=row.recommendation.value,
        comment=row.comment,
    )


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
    scorecard_rows: dict[uuid.UUID, list[Scorecard]] = {}
    activity_rows: dict[uuid.UUID, list[ActivityLog]] = {}
    email_rows: dict[uuid.UUID, list[EmailOutbox]] = {}
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
        # submitted rows only: open, declined and dismissed hold no assessment
        for scorecard in (
            (
                await db.execute(
                    select(Scorecard)
                    .where(
                        Scorecard.application_id.in_(app_ids),
                        Scorecard.submitted_at.is_not(None),
                    )
                    .order_by(Scorecard.submitted_at)
                )
            )
            .scalars()
            .all()
        ):
            scorecard_rows.setdefault(scorecard.application_id, []).append(scorecard)
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
        for mail in (
            (
                await db.execute(
                    select(EmailOutbox)
                    .where(
                        EmailOutbox.company_id == company.id,
                        EmailOutbox.application_id.in_(app_ids),
                    )
                    .order_by(EmailOutbox.created_at)
                )
            )
            .scalars()
            .all()
        ):
            assert mail.application_id is not None  # filtered by the IN clause
            email_rows.setdefault(mail.application_id, []).append(mail)
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
            "privacy_notice_url": urls.privacy_notice_url(company),
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
                rejection_reason=(
                    rejection_reasons.label(application.rejection_reason)
                    if application.rejection_reason is not None
                    else None
                ),
                rejection_note=application.rejection_note,
                applied_at=application.created_at,
                cv_download_url=(
                    storage.presign_cv_download(application.cv_object_key, application.cv_filename)
                    if application.cv_object_key
                    else None
                ),
                screening_answers=[
                    StatusScreeningAnswer(prompt=answer["prompt"], answer=answer["answer"])
                    for answer in application.screening_answers
                ],
                quiz_attempts=[_attempt_out(a) for a in application.quiz_attempts],
                interviews=[
                    DsarInterview(
                        title=interview.title,
                        timezone=interview.timezone,
                        location=interview.location,
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
                scorecards=[_scorecard_out(row) for row in scorecard_rows.get(application.id, [])],
                emails=[
                    DsarEmail(
                        kind=mail.kind,
                        status=mail.status.value,
                        send_after=mail.send_after,
                        sent_at=mail.sent_at,
                        cancelled_at=mail.cancelled_at,
                        created_at=mail.created_at,
                    )
                    for mail in email_rows.get(application.id, [])
                ],
                activity=[
                    DsarActivityEntry(type=row.type, created_at=row.created_at)
                    for row in activity_rows.get(application.id, [])
                ],
            )
            for application in applications
        ],
    )
