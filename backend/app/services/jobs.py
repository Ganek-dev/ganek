import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Company, Job, JobStatus
from app.schemas.jobs import JobCreate, JobUpdate
from app.services.slugs import slugify, with_random_suffix


class InvalidTransitionError(Exception):
    def __init__(self, current: JobStatus, target: JobStatus) -> None:
        super().__init__(f"cannot go from {current.value} to {target.value}")
        self.current = current
        self.target = target


async def _unique_slug(db: AsyncSession, company_id: uuid.UUID, base: str) -> str:
    slug = base
    while True:
        exists = (
            await db.execute(
                select(func.count())
                .select_from(Job)
                .where(Job.company_id == company_id, Job.slug == slug)
            )
        ).scalar_one()
        if not exists:
            return slug
        slug = with_random_suffix(base)


async def create_job(db: AsyncSession, company: Company, payload: JobCreate) -> Job:
    job = Job(
        company_id=company.id,
        slug=await _unique_slug(db, company.id, slugify(payload.title)),
        **payload.model_dump(),
    )
    db.add(job)
    await db.commit()
    return job


async def get_job(db: AsyncSession, company: Company, job_id: uuid.UUID) -> Job | None:
    return (
        await db.execute(select(Job).where(Job.company_id == company.id, Job.id == job_id))
    ).scalar_one_or_none()


async def list_jobs(
    db: AsyncSession, company: Company, *, status: JobStatus | None = None
) -> list[Job]:
    query = select(Job).where(Job.company_id == company.id).order_by(Job.created_at.desc())
    if status is not None:
        query = query.where(Job.status == status)
    return list((await db.execute(query)).scalars().all())


async def update_job(db: AsyncSession, job: Job, payload: JobUpdate) -> Job:
    values = payload.model_dump(exclude_unset=True)
    for field, value in values.items():
        setattr(job, field, value)
    if (
        job.salary_min is not None
        and job.salary_max is not None
        and job.salary_min > job.salary_max
    ):
        raise ValueError("salary_min cannot exceed salary_max")
    await db.commit()
    # updated_at is server-generated (onupdate); refresh so serialization
    # never triggers lazy IO outside the async context
    await db.refresh(job)
    return job


async def publish_job(db: AsyncSession, job: Job) -> Job:
    if job.status not in (JobStatus.DRAFT, JobStatus.CLOSED):
        raise InvalidTransitionError(job.status, JobStatus.PUBLISHED)
    job.status = JobStatus.PUBLISHED
    job.published_at = datetime.now(UTC)
    await db.commit()
    await db.refresh(job)
    return job


async def close_job(db: AsyncSession, job: Job) -> Job:
    if job.status is not JobStatus.PUBLISHED:
        raise InvalidTransitionError(job.status, JobStatus.CLOSED)
    job.status = JobStatus.CLOSED
    await db.commit()
    await db.refresh(job)
    return job


async def delete_job(db: AsyncSession, job: Job) -> None:
    if job.status is not JobStatus.DRAFT:
        raise InvalidTransitionError(job.status, JobStatus.DRAFT)
    await db.delete(job)
    await db.commit()
