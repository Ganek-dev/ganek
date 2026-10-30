import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from sqlalchemy import Select, SQLColumnExpression, cast, func, literal, or_, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sqlalchemy.sql.elements import ColumnElement
from sqlalchemy.sql.selectable import ScalarSelect

from app.core.config import settings
from app.core.sources import normalize_source
from app.models import Application, ApplicationStage, Candidate, Company, Job
from app.models.quiz import AttemptStatus, QuizAttempt
from app.schemas.public import ApplicationSubmit
from app.services import activity, rejection_reasons, storage, webhooks

TERMINAL_STAGES = frozenset(
    {ApplicationStage.REJECTED, ApplicationStage.WITHDRAWN, ApplicationStage.HIRED}
)


def stamp_decision(application: Application, stage: ApplicationStage) -> None:
    """The retention clock (G3): a terminal stage starts it, reopening clears
    it - a re-considered candidate must never be purged from a stale clock."""
    application.decided_at = datetime.now(UTC) if stage in TERMINAL_STAGES else None


REASON_STAGES = frozenset({ApplicationStage.REJECTED, ApplicationStage.WITHDRAWN})


def move_stage(
    application: Application,
    stage: ApplicationStage,
    *,
    reason: str | None = None,
    note: str | None = None,
) -> ApplicationStage:
    """The one way to write a stage: retention clock, stage-age stamp, the
    rejection reason, the assignment. Returns the previous stage; a no-op
    move stamps nothing. The reason and note are written on a move into
    rejected or withdrawn and cleared on a move out of them."""
    previous = application.stage
    if previous is not stage:
        stamp_decision(application, stage)
        if stage in REASON_STAGES:
            application.rejection_reason = reason
            application.rejection_note = note
        elif previous in REASON_STAGES:
            application.rejection_reason = None
            application.rejection_note = None
        application.stage = stage
        application.stage_changed_at = datetime.now(UTC)
    return previous


def _reason_payload(
    stage: ApplicationStage, reason: str | None, note: str | None
) -> dict[str, Any]:
    """The stage.changed payload keys that keep the reason in history."""
    if stage not in REASON_STAGES:
        return {}
    payload: dict[str, Any] = {}
    if reason is not None:
        payload["reason"] = reason
    if note is not None:
        payload["note"] = note
    return payload


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
        raise InvalidCvError("CV upload not found - upload the file first")
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
        source=normalize_source(payload.source),
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


SortKey = Literal[
    "applied_desc",
    "applied_asc",
    "score_desc",
    "score_asc",
    "name_asc",
    "stage_age_desc",
    "stage_age_asc",
]
QuizState = Literal["none", "pending", "in_progress", "completed", "expired"]

SEARCH_MAX_LENGTH = 200
EXPORT_IDS_MAX = 100


@dataclass(frozen=True)
class ListFilters:
    """What the applicant list, its stage counts and its export share, so
    the file a recruiter downloads is always the rows on screen.

    `q` searches candidate name and email (substring, case-insensitive,
    LIKE wildcards in the text are literal). `score_min` is a percent of the
    latest attempt. `quiz` reads the latest attempt; a pending link past its
    expiry counts as expired even before the candidate clicks it (the column
    only flips on that visit). `source == "direct"` also matches NULL (an
    application without a recorded source). `since_days` is a window on
    `created_at`. `ids` restricts to a selection (bulk export).
    """

    job_id: uuid.UUID | None = None
    stage: ApplicationStage | None = None
    q: str | None = None
    score_min: int | None = None
    quiz: QuizState | None = None
    source: str | None = None
    flagged: bool | None = None
    since_days: int | None = None
    ids: tuple[uuid.UUID, ...] = ()


def _latest_attempt_id() -> ScalarSelect[uuid.UUID]:
    """The attempt that counts, matching `Application.quiz_attempt`: the
    newest row; older ones are re-issue history."""
    return (
        select(QuizAttempt.id)
        .where(QuizAttempt.application_id == Application.id)
        .order_by(QuizAttempt.created_at.desc(), QuizAttempt.id.desc())
        .limit(1)
        .correlate(Application)
        .scalar_subquery()
    )


def _escape_like(text: str) -> str:
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _flag_count() -> ColumnElement[int]:
    return func.jsonb_array_length(
        func.coalesce(QuizAttempt.integrity["flags"], cast(literal("[]"), JSONB))
    )


def _conditions(
    company: Company, filters: ListFilters, *, include_stage: bool
) -> list[ColumnElement[bool]]:
    conditions: list[ColumnElement[bool]] = [Application.company_id == company.id]
    if filters.job_id is not None:
        conditions.append(Application.job_id == filters.job_id)
    if include_stage and filters.stage is not None:
        conditions.append(Application.stage == filters.stage)
    if filters.ids:
        conditions.append(Application.id.in_(filters.ids))
    if filters.q:
        pattern = f"%{_escape_like(filters.q.strip())}%"
        conditions.append(
            or_(
                Candidate.name.ilike(pattern, escape="\\"),
                Candidate.email.ilike(pattern, escape="\\"),
            )
        )
    if filters.score_min is not None:
        conditions.append(QuizAttempt.score >= filters.score_min / 100)
    if filters.quiz is not None:
        now = datetime.now(UTC)
        if filters.quiz == "none":
            conditions.append(QuizAttempt.id.is_(None))
        elif filters.quiz == "pending":
            conditions.append(QuizAttempt.status == AttemptStatus.PENDING)
            conditions.append(QuizAttempt.expires_at >= now)
        elif filters.quiz == "expired":
            conditions.append(
                or_(
                    QuizAttempt.status == AttemptStatus.EXPIRED,
                    (QuizAttempt.status == AttemptStatus.PENDING) & (QuizAttempt.expires_at < now),
                )
            )
        else:
            conditions.append(QuizAttempt.status == AttemptStatus(filters.quiz))
    if filters.source is not None:
        if filters.source == "direct":
            conditions.append(or_(Application.source.is_(None), Application.source == "direct"))
        else:
            conditions.append(Application.source == filters.source)
    if filters.flagged is True:
        conditions.append(_flag_count() > 0)
    elif filters.flagged is False:
        conditions.append(or_(QuizAttempt.id.is_(None), _flag_count() == 0))
    if filters.since_days is not None:
        conditions.append(
            Application.created_at >= datetime.now(UTC) - timedelta(days=filters.since_days)
        )
    return conditions


def _filtered(
    company: Company, filters: ListFilters, *columns: Any, include_stage: bool = True
) -> Select[Any]:
    """A select over applications joined to the candidate and the latest
    attempt, narrowed by the filters. Always joins: the planner skips the
    unused ones cheaply and the ordering clauses need them anyway."""
    return (
        select(*columns)
        .select_from(Application)
        .join(Candidate, Candidate.id == Application.candidate_id)
        .outerjoin(QuizAttempt, QuizAttempt.id == _latest_attempt_id())
        .where(*_conditions(company, filters, include_stage=include_stage))
    )


def _order_by(sort: SortKey) -> list[SQLColumnExpression[Any]]:
    newest: list[SQLColumnExpression[Any]] = [Application.created_at.desc(), Application.id]
    if sort == "applied_asc":
        return [Application.created_at.asc(), Application.id]
    if sort == "score_desc":
        return [QuizAttempt.score.desc().nulls_last(), *newest]
    if sort == "score_asc":
        return [QuizAttempt.score.asc().nulls_last(), *newest]
    if sort == "name_asc":
        return [func.lower(Candidate.name), *newest]
    if sort == "stage_age_desc":  # longest in the current stage first
        return [Application.stage_changed_at.asc(), Application.id]
    if sort == "stage_age_asc":
        return [Application.stage_changed_at.desc(), Application.id]
    return newest


async def list_applications(
    db: AsyncSession,
    company: Company,
    *,
    filters: ListFilters | None = None,
    sort: SortKey = "applied_desc",
    limit: int = 100,
    offset: int = 0,
) -> tuple[list[Application], int]:
    """One page of the pipeline plus the total the filters match.

    M5.7 H4: the old version materialized every row (candidate + all quiz
    attempts + integrity JSONB) per visit - the first scale cliff.
    """
    filters = filters or ListFilters()
    total = (await db.execute(_filtered(company, filters, func.count()))).scalar_one()
    query = (
        _filtered(company, filters, Application)
        .options(
            selectinload(Application.candidate),
            selectinload(Application.quiz_attempts),
        )
        .order_by(*_order_by(sort))
        .limit(limit)
        .offset(offset)
    )
    return list((await db.execute(query)).scalars().all()), total


async def list_sources(db: AsyncSession, company: Company) -> list[str]:
    """The source facet: every distinct value this company has seen, NULL
    folded into "direct", sorted. Company-wide on purpose so an empty
    result still offers the options."""
    rows = await db.execute(
        select(func.coalesce(Application.source, "direct"))
        .where(Application.company_id == company.id)
        .distinct()
    )
    return sorted(str(value) for (value,) in rows.all())


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
    "rejection_reason",
    "rejection_note",
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
        # internal rejection reason (PR 2): the label, for the team's sheet
        "rejection_reason": rejection_reasons.label(application.rejection_reason),
        "rejection_note": application.rejection_note or "",
    }


async def export_applications(
    db: AsyncSession,
    company: Company,
    *,
    filters: ListFilters | None = None,
) -> list[dict[str, str | int]]:
    """Every application the filters match, oldest first, as export rows."""
    query = (
        _filtered(company, filters or ListFilters(), Application)
        .options(
            selectinload(Application.candidate),
            selectinload(Application.job),
            selectinload(Application.quiz_attempts),
        )
        .order_by(Application.created_at, Application.id)
    )
    return [export_row(app) for app in (await db.execute(query)).scalars().all()]


async def count_by_stage(
    db: AsyncSession, company: Company, *, filters: ListFilters | None = None
) -> dict[str, int]:
    """Pipeline pill counts for the WHOLE filtered set (the stage filter
    never applies - the pills are how you switch stages)."""
    rows = await db.execute(
        _filtered(
            company, filters or ListFilters(), Application.stage, func.count(), include_stage=False
        ).group_by(Application.stage)
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
    """Token-authenticated candidate lookup (status page) - no tenancy scope;
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
    reason: str | None = None,
    note: str | None = None,
) -> Application:
    previous = move_stage(application, stage, reason=reason, note=note)
    if previous is not stage:
        activity.record(
            db,
            company_id=application.company_id,
            type=activity.STAGE_CHANGED,
            actor_user_id=actor_user_id,
            application_id=application.id,
            payload={
                "from": previous.value,
                "to": stage.value,
                **_reason_payload(stage, reason, note),
            },
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
    """Art. 16 rectification - the address is the delivery channel for every
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


async def bulk_set_stage(
    db: AsyncSession,
    company: Company,
    application_ids: list[uuid.UUID],
    stage: ApplicationStage,
    *,
    actor_user_id: uuid.UUID | None = None,
    reason: str | None = None,
    note: str | None = None,
) -> list[Application]:
    """Move every listed application the actor may move to `stage`.

    Rows already there, withdrawn rows (the candidate's call, never
    overridden), ids from another tenant and unknown ids are skipped
    silently; the route derives `skipped` from the count difference. Each
    moved row gets its own `stage.changed` activity entry (payload marks
    `bulk`) and webhook, so the trail reads the same as single moves.
    """
    applications = list(
        (
            await db.execute(
                select(Application)
                .where(
                    Application.company_id == company.id,
                    Application.id.in_(application_ids),
                    Application.stage != stage,
                    Application.stage != ApplicationStage.WITHDRAWN,
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
    moved: list[tuple[Application, ApplicationStage]] = []
    for application in applications:
        previous = move_stage(application, stage, reason=reason, note=note)
        activity.record(
            db,
            company_id=company.id,
            type=activity.STAGE_CHANGED,
            actor_user_id=actor_user_id,
            application_id=application.id,
            payload={
                "from": previous.value,
                "to": stage.value,
                "bulk": True,
                **_reason_payload(stage, reason, note),
            },
        )
        moved.append((application, previous))
    await db.commit()
    for application, previous in moved:
        await webhooks.emit_application_event(
            db, application.id, "stage.changed", {"previous_stage": previous.value}
        )
    return applications


async def bulk_reject(
    db: AsyncSession,
    company: Company,
    application_ids: list[uuid.UUID],
    *,
    actor_user_id: uuid.UUID | None = None,
    reason: str | None = None,
    note: str | None = None,
) -> list[Application]:
    """Reject every listed application that's still open.

    Already-rejected/withdrawn rows, ids from another tenant, and unknown
    ids are silently excluded from the result rather than erroring - the
    route derives `skipped` from the count difference. One summary activity
    entry covers the whole call for the dashboard feed (only recorded when
    something was rejected) plus one `stage.changed{bulk: true}` per row so
    the applicant timeline shows who rejected whom.
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
        previous = move_stage(application, ApplicationStage.REJECTED, reason=reason, note=note)
        activity.record(
            db,
            company_id=company.id,
            type=activity.STAGE_CHANGED,
            actor_user_id=actor_user_id,
            application_id=application.id,
            payload={
                "from": previous.value,
                "to": ApplicationStage.REJECTED.value,
                "bulk": True,
                **_reason_payload(ApplicationStage.REJECTED, reason, note),
            },
        )
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
