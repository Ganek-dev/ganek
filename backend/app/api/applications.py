import math
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, BackgroundTasks, HTTPException, status

from app.api.deps import CurrentCompany, DbSession
from app.core.config import settings
from app.core.security import create_quiz_token, create_status_token
from app.models import Application, ApplicationStage
from app.models.quiz import AttemptStatus
from app.schemas.applications import (
    ApplicationOut,
    CvDownload,
    QuizAnswerReview,
    ReviewIntegrityEvent,
    StageUpdate,
)
from app.services import applications as applications_service
from app.services import email as email_service
from app.services import quiz as quiz_service
from app.services import storage

router = APIRouter(prefix="/applications", tags=["applications"])


async def _get_or_404(
    db: DbSession, company: CurrentCompany, application_id: uuid.UUID
) -> Application:
    application = await applications_service.get_application(db, company, application_id)
    if application is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Application not found")
    return application


@router.get("", response_model=list[ApplicationOut])
async def list_applications(
    db: DbSession,
    company: CurrentCompany,
    job_id: uuid.UUID | None = None,
    stage: ApplicationStage | None = None,
) -> list[Application]:
    return await applications_service.list_applications(db, company, job_id=job_id, stage=stage)


@router.get("/{application_id}", response_model=ApplicationOut)
async def get_application(
    application_id: uuid.UUID, db: DbSession, company: CurrentCompany
) -> Application:
    return await _get_or_404(db, company, application_id)


@router.patch("/{application_id}/stage", response_model=ApplicationOut)
async def set_stage(
    application_id: uuid.UUID,
    payload: StageUpdate,
    db: DbSession,
    company: CurrentCompany,
    background: BackgroundTasks,
) -> Application:
    application = await _get_or_404(db, company, application_id)
    updated = await applications_service.set_stage(db, application, payload.stage)
    if payload.notify_candidate:
        _schedule_stage_email(background, company, application, payload.stage)
    return updated


@router.post("/{application_id}/remind", response_model=dict[str, bool])
async def remind_candidate(
    application_id: uuid.UUID,
    db: DbSession,
    company: CurrentCompany,
    background: BackgroundTasks,
) -> dict[str, bool]:
    """Manually resend the assessment link (17b) while the attempt is untouched."""
    application = await _get_or_404(db, company, application_id)
    attempt = application.quiz_attempt
    now = datetime.now(UTC)
    if attempt is None or attempt.status is not AttemptStatus.PENDING or attempt.expires_at <= now:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="No pending assessment to remind about",
        )
    days_left = max(0, math.ceil((attempt.expires_at - now).total_seconds() / 86400))
    background.add_task(
        email_service.send_quiz_reminder,
        to=application.candidate.email,
        candidate_name=application.candidate.name,
        job_title=application.job.title,
        company_name=company.name,
        brand_primary=(company.theme or {}).get("primary_color"),
        quiz_url=f"{settings.public_base_url.rstrip('/')}/quiz/{create_quiz_token(attempt.id)}",
        expires_at=attempt.expires_at,
        days_left=days_left,
    )
    return {"sent": True}


def _schedule_stage_email(
    background: BackgroundTasks,
    company: CurrentCompany,
    application: Application,
    stage: ApplicationStage,
) -> None:
    """Queue 22a/22b for stages with a template; other stages are a no-op."""
    candidate = application.candidate
    job = application.job
    base = settings.public_base_url.rstrip("/")
    if stage is ApplicationStage.INTERVIEW:
        background.add_task(
            email_service.send_stage_advance,
            to=candidate.email,
            candidate_name=candidate.name,
            job_title=job.title,
            company_name=company.name,
            brand_primary=(company.theme or {}).get("primary_color"),
            status_url=f"{base}/application/{create_status_token(application.id)}",
        )
    elif stage is ApplicationStage.REJECTED:
        careers_url = base if settings.mode == "single" else f"{base}/c/{company.slug}"
        attempt = application.quiz_attempt
        background.add_task(
            email_service.send_rejection,
            to=candidate.email,
            candidate_name=candidate.name,
            job_title=job.title,
            company_name=company.name,
            careers_url=careers_url,
            completed_assessment=attempt is not None and attempt.completed_at is not None,
        )


@router.get("/{application_id}/cv-url", response_model=CvDownload)
async def cv_download_url(
    application_id: uuid.UUID, db: DbSession, company: CurrentCompany
) -> CvDownload:
    application = await _get_or_404(db, company, application_id)
    return CvDownload(
        download_url=storage.presign_cv_download(application.cv_object_key, application.cv_filename)
    )


@router.get("/{application_id}/quiz-answers", response_model=list[QuizAnswerReview])
async def quiz_answers(
    application_id: uuid.UUID, db: DbSession, company: CurrentCompany
) -> list[QuizAnswerReview]:
    application = await _get_or_404(db, company, application_id)
    attempt = await quiz_service.get_attempt_by_application(db, application.id)
    if attempt is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="No quiz for this application"
        )
    events = attempt.integrity.get("events", [])
    reviews: list[QuizAnswerReview] = []
    for answer, question in await quiz_service.review_answers(db, attempt):
        response_ms: int | None = None
        if answer.answer_key is not None and answer.answered_at is not None:
            response_ms = int((answer.answered_at - answer.served_at).total_seconds() * 1000)
        question_events = [
            ReviewIntegrityEvent(type=str(e.get("type")), duration_ms=e.get("duration_ms"))
            for e in events
            if e.get("question_id") == question.id
        ]
        reviews.append(
            QuizAnswerReview(
                question_id=question.id,
                prompt_md=question.prompt_md,
                options=question.options,
                correct_key=question.correct_key,
                explanation_md=question.explanation_md,
                tags=question.tags,
                answer_key=answer.answer_key,
                is_correct=answer.is_correct,
                response_ms=response_ms,
                integrity_events=question_events,
            )
        )
    return reviews
