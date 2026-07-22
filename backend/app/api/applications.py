import uuid

from fastapi import APIRouter, HTTPException, status

from app.api.deps import CurrentCompany, DbSession
from app.models import Application, ApplicationStage
from app.schemas.applications import (
    ApplicationOut,
    CvDownload,
    QuizAnswerReview,
    StageUpdate,
)
from app.services import applications as applications_service
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
    application_id: uuid.UUID, payload: StageUpdate, db: DbSession, company: CurrentCompany
) -> Application:
    application = await _get_or_404(db, company, application_id)
    return await applications_service.set_stage(db, application, payload.stage)


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
    reviews: list[QuizAnswerReview] = []
    for answer, question in await quiz_service.review_answers(db, attempt):
        response_ms: int | None = None
        if answer.answer_key is not None and answer.answered_at is not None:
            response_ms = int((answer.answered_at - answer.served_at).total_seconds() * 1000)
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
            )
        )
    return reviews
