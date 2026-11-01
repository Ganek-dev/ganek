import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, HTTPException, status

from app.api.deps import AdminUser, DbSession, StaffCompany
from app.core import urls
from app.core.config import settings
from app.core.security import PREVIEW_TOKEN_MAX_AGE_SECONDS, create_preview_token
from app.models import Job, JobStatus
from app.schemas.jobs import (
    JobCreate,
    JobOut,
    JobUpdate,
    PreviewLinkOut,
    QuizPreviewOut,
    QuizPreviewQuestion,
)
from app.schemas.stats import JobStats
from app.services import jobs as jobs_service
from app.services import quiz as quiz_service
from app.services import quotas
from app.services import stats as stats_service

router = APIRouter(prefix="/jobs", tags=["jobs"])


async def _get_or_404(db: DbSession, company: StaffCompany, job_id: uuid.UUID) -> Job:
    job = await jobs_service.get_job(db, company, job_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
    return job


@router.get("", response_model=list[JobOut])
async def list_jobs(
    db: DbSession, company: StaffCompany, status_filter: JobStatus | None = None
) -> list[Job]:
    return await jobs_service.list_jobs(db, company, status=status_filter)


@router.post("", response_model=JobOut, status_code=status.HTTP_201_CREATED)
async def create_job(payload: JobCreate, db: DbSession, company: StaffCompany) -> Job:
    try:
        return await jobs_service.create_job(db, company, payload)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
        ) from None


@router.get("/{job_id}", response_model=JobOut)
async def get_job(job_id: uuid.UUID, db: DbSession, company: StaffCompany) -> Job:
    return await _get_or_404(db, company, job_id)


@router.patch("/{job_id}", response_model=JobOut)
async def update_job(
    job_id: uuid.UUID, payload: JobUpdate, db: DbSession, company: StaffCompany
) -> Job:
    job = await _get_or_404(db, company, job_id)
    try:
        return await jobs_service.update_job(db, company, job, payload)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
        ) from None


@router.get("/{job_id}/quiz-preview", response_model=QuizPreviewOut)
async def quiz_preview(job_id: uuid.UUID, db: DbSession, company: StaffCompany) -> QuizPreviewOut:
    """What this job's quiz draws from right now. Read-only; sample redraws per call."""
    job = await _get_or_404(db, company, job_id)
    config, pool, eligible_ids, sample = await quiz_service.build_quiz_preview(db, company, job)
    blocked = set(company.blocked_question_ids or [])
    excluded = set(config.exclude_ids)
    return QuizPreviewOut(
        enabled=config.enabled,
        tags=config.tags,
        question_count=config.question_count,
        time_limit_seconds=config.time_limit_seconds,
        difficulties=config.difficulties,
        pool=[
            QuizPreviewQuestion(
                id=question.id,
                source=question.source.value,
                tags=question.tags,
                difficulty=question.difficulty,
                prompt_md=question.prompt_md,
                options=question.options,
                correct_key=question.correct_key,
                excluded=question.id in excluded,
                blocked=question.id in blocked,
            )
            for question in pool
        ],
        eligible_count=len(eligible_ids),
        eligible_by_tag={
            tag: sum(1 for q in pool if q.id in eligible_ids and tag in q.tags)
            for tag in config.tags
        },
        sample_question_ids=sample,
    )


@router.get("/{job_id}/stats", response_model=JobStats)
async def job_stats(job_id: uuid.UUID, db: DbSession, company: StaffCompany) -> JobStats:
    """Overview counts for one job (applications by stage, quiz, weekly, days open)."""
    job = await _get_or_404(db, company, job_id)
    return await stats_service.job_stats(db, company, job)


@router.post("/{job_id}/preview-link", response_model=PreviewLinkOut)
async def preview_link(job_id: uuid.UUID, db: DbSession, company: StaffCompany) -> PreviewLinkOut:
    """A 7-day link that shows this job as candidates will see it, published
    or not; shareable with a colleague who has no login (spec 5.3)."""
    job = await _get_or_404(db, company, job_id)
    token = create_preview_token(job.id)
    return PreviewLinkOut(
        url=f"{urls.job_url(company, job.slug)}?preview={token}",
        expires_at=datetime.now(UTC) + timedelta(seconds=PREVIEW_TOKEN_MAX_AGE_SECONDS),
    )


@router.post("/{job_id}/publish", response_model=JobOut)
async def publish_job(job_id: uuid.UUID, db: DbSession, company: StaffCompany) -> Job:
    job = await _get_or_404(db, company, job_id)
    limit = settings.quota_active_jobs
    if limit > 0 and job.status is not JobStatus.PUBLISHED:
        if await quotas.active_jobs(db, company) >= limit:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    f"Active job limit reached ({limit}). Close a job before publishing another."
                ),
            )
    try:
        return await jobs_service.publish_job(db, job)
    except jobs_service.InvalidTransitionError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from None


@router.post("/{job_id}/close", response_model=JobOut)
async def close_job(job_id: uuid.UUID, db: DbSession, company: StaffCompany) -> Job:
    job = await _get_or_404(db, company, job_id)
    try:
        return await jobs_service.close_job(db, job)
    except jobs_service.InvalidTransitionError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from None


@router.delete("/{job_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_job(
    job_id: uuid.UUID, db: DbSession, company: StaffCompany, _admin: AdminUser
) -> None:
    job = await _get_or_404(db, company, job_id)
    try:
        await jobs_service.delete_job(db, job)
    except jobs_service.InvalidTransitionError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from None
