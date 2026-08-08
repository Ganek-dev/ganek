import uuid

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.models import Application, ApplicationStage, Candidate, Company, Job
from app.schemas.public import ApplicationSubmit
from app.services import activity, storage


class AlreadyAppliedError(Exception):
    """This candidate already applied to this job."""


class InvalidCvError(Exception):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


async def _validated_cv(company: Company, payload: ApplicationSubmit) -> storage.ObjectStat:
    if not payload.cv_object_key.startswith(f"cvs/{company.id}/"):
        raise InvalidCvError("CV reference does not belong to this company")
    stat = await storage.stat_object(payload.cv_object_key)
    if stat is None:
        raise InvalidCvError("CV upload not found — upload the file first")
    if stat.size > settings.cv_max_size_mb * 1024 * 1024:
        raise InvalidCvError(f"CV exceeds the {settings.cv_max_size_mb} MB limit")
    if stat.content_type != storage.CV_CONTENT_TYPE:
        raise InvalidCvError("CV must be a PDF")
    return stat


async def _get_or_create_candidate(
    db: AsyncSession, company: Company, payload: ApplicationSubmit
) -> Candidate:
    candidate = (
        await db.execute(
            select(Candidate).where(
                Candidate.company_id == company.id, Candidate.email == payload.email
            )
        )
    ).scalar_one_or_none()
    if candidate is None:
        candidate = Candidate(company_id=company.id, email=payload.email, name=payload.name)
        db.add(candidate)
    candidate.name = payload.name
    candidate.links = payload.links()
    await db.flush()
    return candidate


async def submit_application(
    db: AsyncSession, company: Company, job: Job, payload: ApplicationSubmit
) -> Application:
    stat = await _validated_cv(company, payload)
    candidate = await _get_or_create_candidate(db, company, payload)
    application = Application(
        company_id=company.id,
        job_id=job.id,
        candidate_id=candidate.id,
        cv_object_key=payload.cv_object_key,
        cv_filename=payload.cv_filename,
        cv_size=stat.size,
        message=payload.message,
    )
    db.add(application)
    try:
        await db.flush()
        activity.record(
            db,
            company_id=company.id,
            type=activity.APPLICATION_RECEIVED,
            application_id=application.id,
            payload={"candidate": candidate.name, "job": job.title},
        )
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise AlreadyAppliedError from None
    return application


async def list_applications(
    db: AsyncSession,
    company: Company,
    *,
    job_id: uuid.UUID | None = None,
    stage: ApplicationStage | None = None,
) -> list[Application]:
    query = (
        select(Application)
        .where(Application.company_id == company.id)
        .options(
            selectinload(Application.candidate),
            selectinload(Application.quiz_attempts),
        )
        .order_by(Application.created_at.desc())
    )
    if job_id is not None:
        query = query.where(Application.job_id == job_id)
    if stage is not None:
        query = query.where(Application.stage == stage)
    return list((await db.execute(query)).scalars().all())


async def get_application(
    db: AsyncSession, company: Company, application_id: uuid.UUID
) -> Application | None:
    return (
        await db.execute(
            select(Application)
            .where(Application.company_id == company.id, Application.id == application_id)
            .options(
                selectinload(Application.candidate),
                selectinload(Application.quiz_attempts),
                selectinload(Application.job),
            )
        )
    ).scalar_one_or_none()


async def get_application_by_id(db: AsyncSession, application_id: uuid.UUID) -> Application | None:
    """Token-authenticated candidate lookup (status page) — no tenancy scope;
    the signed status token is the authorization."""
    return (
        await db.execute(
            select(Application)
            .where(Application.id == application_id)
            .options(
                selectinload(Application.candidate),
                selectinload(Application.quiz_attempts),
                selectinload(Application.job),
            )
        )
    ).scalar_one_or_none()


async def set_stage(
    db: AsyncSession,
    application: Application,
    stage: ApplicationStage,
    *,
    actor_user_id: uuid.UUID | None = None,
) -> Application:
    previous = application.stage
    application.stage = stage
    if previous is not stage:
        activity.record(
            db,
            company_id=application.company_id,
            type=activity.STAGE_CHANGED,
            actor_user_id=actor_user_id,
            application_id=application.id,
            payload={"from": previous.value, "to": stage.value},
        )
    await db.commit()
    await db.refresh(application)
    return application
