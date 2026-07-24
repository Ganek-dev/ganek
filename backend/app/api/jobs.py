import uuid

from fastapi import APIRouter, HTTPException, status

from app.api.deps import AdminUser, CurrentCompany, DbSession
from app.models import Job, JobStatus
from app.schemas.jobs import JobCreate, JobOut, JobUpdate
from app.services import jobs as jobs_service

router = APIRouter(prefix="/jobs", tags=["jobs"])


async def _get_or_404(db: DbSession, company: CurrentCompany, job_id: uuid.UUID) -> Job:
    job = await jobs_service.get_job(db, company, job_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
    return job


@router.get("", response_model=list[JobOut])
async def list_jobs(
    db: DbSession, company: CurrentCompany, status_filter: JobStatus | None = None
) -> list[Job]:
    return await jobs_service.list_jobs(db, company, status=status_filter)


@router.post("", response_model=JobOut, status_code=status.HTTP_201_CREATED)
async def create_job(payload: JobCreate, db: DbSession, company: CurrentCompany) -> Job:
    return await jobs_service.create_job(db, company, payload)


@router.get("/{job_id}", response_model=JobOut)
async def get_job(job_id: uuid.UUID, db: DbSession, company: CurrentCompany) -> Job:
    return await _get_or_404(db, company, job_id)


@router.patch("/{job_id}", response_model=JobOut)
async def update_job(
    job_id: uuid.UUID, payload: JobUpdate, db: DbSession, company: CurrentCompany
) -> Job:
    job = await _get_or_404(db, company, job_id)
    try:
        return await jobs_service.update_job(db, job, payload)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
        ) from None


@router.post("/{job_id}/publish", response_model=JobOut)
async def publish_job(job_id: uuid.UUID, db: DbSession, company: CurrentCompany) -> Job:
    job = await _get_or_404(db, company, job_id)
    try:
        return await jobs_service.publish_job(db, job)
    except jobs_service.InvalidTransitionError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from None


@router.post("/{job_id}/close", response_model=JobOut)
async def close_job(job_id: uuid.UUID, db: DbSession, company: CurrentCompany) -> Job:
    job = await _get_or_404(db, company, job_id)
    try:
        return await jobs_service.close_job(db, job)
    except jobs_service.InvalidTransitionError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from None


@router.delete("/{job_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_job(
    job_id: uuid.UUID, db: DbSession, company: CurrentCompany, _admin: AdminUser
) -> None:
    job = await _get_or_404(db, company, job_id)
    try:
        await jobs_service.delete_job(db, job)
    except jobs_service.InvalidTransitionError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from None
