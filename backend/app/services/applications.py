import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.models import Application, ApplicationStage, Candidate, Company, Job
from app.schemas.public import ApplicationSubmit
from app.services import activity, storage, webhooks

TERMINAL_STAGES = frozenset(
    {ApplicationStage.REJECTED, ApplicationStage.WITHDRAWN, ApplicationStage.HIRED}
)


def stamp_decision(application: Application, stage: ApplicationStage) -> None:
    """The retention clock (G3): a terminal stage starts it, reopening clears
    it — a re-considered candidate must never be purged from a stale clock."""
    application.decided_at = datetime.now(UTC) if stage in TERMINAL_STAGES else None


class AlreadyAppliedError(Exception):
    """This candidate already applied to this job."""


class InvalidCvError(Exception):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


async def _validated_cv(company: Company, object_key: str) -> storage.ObjectStat:
    if not object_key.startswith(f"cvs/{company.id}/"):
        raise InvalidCvError("CV reference does not belong to this company")
    stat = await storage.stat_object(object_key)
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
    if payload.cv_object_key is None or payload.cv_filename is None:
        raise InvalidCvError("CV is required")
    stat = await _validated_cv(company, payload.cv_object_key)
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
    await webhooks.emit_application_event(db, application.id, "application.created")
    return application


async def list_applications(
    db: AsyncSession,
    company: Company,
    *,
    job_id: uuid.UUID | None = None,
    stage: ApplicationStage | None = None,
    limit: int = 100,
    offset: int = 0,
) -> tuple[list[Application], int]:
    """One page of the pipeline plus the total the filters match.

    M5.7 H4: the old version materialized every row (candidate + all quiz
    attempts + integrity JSONB) per visit — the first scale cliff.
    """
    conditions = [Application.company_id == company.id]
    if job_id is not None:
        conditions.append(Application.job_id == job_id)
    if stage is not None:
        conditions.append(Application.stage == stage)
    total = (
        await db.execute(select(func.count()).select_from(Application).where(*conditions))
    ).scalar_one()
    query = (
        select(Application)
        .where(*conditions)
        .options(
            selectinload(Application.candidate),
            selectinload(Application.quiz_attempts),
        )
        .order_by(Application.created_at.desc(), Application.id)
        .limit(limit)
        .offset(offset)
    )
    return list((await db.execute(query)).scalars().all()), total


EXPORT_COLUMNS = (
    "candidate_name",
    "candidate_email",
    "job",
    "stage",
    "applied_at",
    "decided_at",
    "source",
    "quiz_status",
    "quiz_score_percent",
    "quiz_completed_at",
    "integrity_flags",
    "quiz_time_multiplier",
    "cv_filename",
    "message",
)


def _iso(value: datetime | None) -> str:
    return value.isoformat() if value is not None else ""


def export_row(application: Application) -> dict[str, str | int]:
    """One flat, spreadsheet-shaped row (card D9). No internal ids: the
    candidate email is the join key an ATS needs, and the quiz columns stay
    at the summary level the list view shows (never answers or keys)."""
    attempt = application.quiz_attempt
    flags = attempt.integrity.get("flags", []) if attempt is not None else []
    return {
        "candidate_name": application.candidate.name,
        "candidate_email": application.candidate.email,
        "job": application.job.title,
        "stage": application.stage.value,
        "applied_at": _iso(application.created_at),
        "decided_at": _iso(application.decided_at),
        "source": application.source or "",
        "quiz_status": attempt.status.value if attempt is not None else "",
        "quiz_score_percent": (
            round(attempt.score * 100) if attempt is not None and attempt.score is not None else ""
        ),
        "quiz_completed_at": _iso(attempt.completed_at) if attempt is not None else "",
        "integrity_flags": "; ".join(str(flag.get("summary", "")) for flag in flags),
        "quiz_time_multiplier": (
            f"{attempt.time_multiplier:g}x"
            if attempt is not None and (attempt.time_multiplier or 1.0) > 1.0
            else ""
        ),
        "cv_filename": application.cv_filename,
        "message": application.message or "",
    }


async def export_applications(
    db: AsyncSession,
    company: Company,
    *,
    job_id: uuid.UUID | None = None,
    stage: ApplicationStage | None = None,
) -> list[dict[str, str | int]]:
    """Every application the filters match, oldest first, as export rows."""
    conditions = [Application.company_id == company.id]
    if job_id is not None:
        conditions.append(Application.job_id == job_id)
    if stage is not None:
        conditions.append(Application.stage == stage)
    query = (
        select(Application)
        .where(*conditions)
        .options(
            selectinload(Application.candidate),
            selectinload(Application.job),
            selectinload(Application.quiz_attempts),
        )
        .order_by(Application.created_at, Application.id)
    )
    return [export_row(app) for app in (await db.execute(query)).scalars().all()]


async def count_by_stage(
    db: AsyncSession, company: Company, *, job_id: uuid.UUID | None = None
) -> dict[str, int]:
    """Pipeline pill counts for the WHOLE filtered set (stage filter never
    applies — the pills are how you switch stages)."""
    conditions = [Application.company_id == company.id]
    if job_id is not None:
        conditions.append(Application.job_id == job_id)
    rows = await db.execute(
        select(Application.stage, func.count()).where(*conditions).group_by(Application.stage)
    )
    return {stage.value: count for stage, count in rows.all()}


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
    stamp_decision(application, stage)
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
    if previous is not stage:
        await webhooks.emit_application_event(
            db, application.id, "stage.changed", {"previous_stage": previous.value}
        )
    return application


class EmailTakenByOtherCandidateError(Exception):
    """The corrected address already belongs to a different candidate row."""


async def update_candidate_email(
    db: AsyncSession,
    company: Company,
    application: Application,
    email: str,
    *,
    actor_user_id: uuid.UUID | None = None,
) -> Application:
    """Art. 16 rectification — the address is the delivery channel for every
    quiz/status/booking link and has no other correction path (a re-apply
    with a new address creates a new candidate row). The value arrives
    EmailStr-validated and is stored verbatim, mirroring the apply flow."""
    existing = (
        await db.execute(
            select(Candidate).where(
                Candidate.company_id == company.id,
                Candidate.email == email,
                Candidate.id != application.candidate_id,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        raise EmailTakenByOtherCandidateError
    application.candidate.email = email
    activity.record(
        db,
        company_id=company.id,
        type=activity.CANDIDATE_EMAIL_UPDATED,
        actor_user_id=actor_user_id,
        application_id=application.id,
        payload={},
    )
    await db.commit()
    await db.refresh(application)
    return application


async def bulk_reject(
    db: AsyncSession,
    company: Company,
    application_ids: list[uuid.UUID],
    *,
    actor_user_id: uuid.UUID | None = None,
) -> list[Application]:
    """Reject every listed application that's still open.

    Already-rejected/withdrawn rows, ids from another tenant, and unknown
    ids are silently excluded from the result rather than erroring — the
    route derives `skipped` from the count difference. One activity entry
    covers the whole call (only recorded when something was rejected).
    """
    applications = list(
        (
            await db.execute(
                select(Application)
                .where(
                    Application.company_id == company.id,
                    Application.id.in_(application_ids),
                    Application.stage.not_in(
                        (ApplicationStage.REJECTED, ApplicationStage.WITHDRAWN)
                    ),
                )
                .options(
                    selectinload(Application.candidate),
                    selectinload(Application.quiz_attempts),
                    selectinload(Application.job),
                )
            )
        )
        .scalars()
        .all()
    )
    for application in applications:
        stamp_decision(application, ApplicationStage.REJECTED)
        application.stage = ApplicationStage.REJECTED
    if applications:
        activity.record(
            db,
            company_id=company.id,
            type=activity.BULK_REJECTED,
            actor_user_id=actor_user_id,
            payload={"count": len(applications)},
        )
    await db.commit()
    return applications
