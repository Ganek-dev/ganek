"""Pipeline signals: the workspace stage limit (stalled-candidate cue).

The setting reader, the pure waiting-on-whom rules, and the open roles board built on them.
"""

import uuid
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal

from sqlalchemy import func, select, union_all
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.activity import ActivityLog
from app.models.application import CLOSED_STAGES, Application, ApplicationStage
from app.models.company import Company
from app.models.interview import Interview, InterviewStatus
from app.models.job import Job, JobStatus
from app.models.quiz import AttemptStatus, QuizAttempt
from app.schemas.stats import BoardJob, BoardOut, BoardStatus, BoardTotals, StageCounts
from app.services.activity import STAGE_CHANGED
from app.services.applications import _latest_attempt_id

STAGE_LIMIT_KEY = "stage_limit_days"
DEFAULT_STAGE_LIMIT_DAYS = 7


def stage_limit(company: Company) -> int:
    """Days a live application may sit in one stage before it is flagged."""
    return int((company.settings or {}).get(STAGE_LIMIT_KEY, DEFAULT_STAGE_LIMIT_DAYS))


Who = Literal["team", "candidate"]


@dataclass(frozen=True)
class AttemptView:
    status: AttemptStatus
    created_at: datetime
    completed_at: datetime | None
    expires_at: datetime


@dataclass(frozen=True)
class InterviewView:
    status: InterviewStatus
    created_at: datetime
    scheduled_start: datetime | None
    duration_minutes: int


@dataclass(frozen=True)
class Waiting:
    who: Who
    since: datetime


def attempt_view(attempt: QuizAttempt | None) -> AttemptView | None:
    if attempt is None:
        return None
    return AttemptView(attempt.status, attempt.created_at, attempt.completed_at, attempt.expires_at)


def interview_view(interview: Interview | None) -> InterviewView | None:
    """None for a cancelled interview: it never counts as the active one."""
    if interview is None or interview.status is InterviewStatus.CANCELLED:
        return None
    return InterviewView(
        interview.status,
        interview.created_at,
        interview.scheduled_start,
        interview.duration_minutes,
    )


def waiting_on(
    stage: ApplicationStage,
    stage_changed_at: datetime,
    attempt: AttemptView | None,
    interview: InterviewView | None,
    now: datetime,
) -> Waiting:
    """Who a live application is waiting on; interview rows first, then stage rows."""
    if interview is not None:
        if interview.status is InterviewStatus.BOOKED and interview.scheduled_start:
            end = interview.scheduled_start + timedelta(minutes=interview.duration_minutes)
            if end <= now:
                return Waiting("team", end)
        return Waiting("candidate", interview.created_at)
    if stage is ApplicationStage.NEW:
        if attempt is not None:
            if attempt.status is AttemptStatus.IN_PROGRESS:
                return Waiting("candidate", attempt.created_at)
            if attempt.status is AttemptStatus.PENDING and attempt.expires_at > now:
                return Waiting("candidate", attempt.created_at)
            if attempt.status is AttemptStatus.COMPLETED and attempt.completed_at:
                return Waiting("team", attempt.completed_at)
            if attempt.status in (AttemptStatus.EXPIRED, AttemptStatus.PENDING):
                return Waiting("team", attempt.expires_at)
        return Waiting("team", stage_changed_at)
    if stage is ApplicationStage.OFFER:
        return Waiting("candidate", stage_changed_at)
    return Waiting("team", stage_changed_at)


def is_overdue(waiting: Waiting, limit_days: int, now: datetime) -> bool:
    """Team waits only; UTC calendar days, as waiting_days in scorecards."""
    if waiting.who != "team":
        return False
    delta = now.astimezone(UTC).date() - waiting.since.astimezone(UTC).date()
    return delta.days > limit_days


def _days_between(later: datetime, earlier: datetime) -> int:
    """UTC calendar days, as `is_overdue` and `waiting_days` in scorecards."""
    return (later.astimezone(UTC).date() - earlier.astimezone(UTC).date()).days


@dataclass(frozen=True)
class LiveRow:
    application: Application
    attempt_view: AttemptView | None
    interview_view: InterviewView | None


async def _load_live(db: AsyncSession, company: Company) -> list[LiveRow]:
    """Live applications of published and closed jobs with the latest attempt and the
    active interview, in three queries."""
    applications = list(
        (
            await db.execute(
                select(Application)
                .join(Job, Job.id == Application.job_id)
                .where(
                    Application.company_id == company.id,
                    Application.stage.not_in(CLOSED_STAGES),
                    Job.status.in_((JobStatus.PUBLISHED, JobStatus.CLOSED)),
                )
                .options(selectinload(Application.job))
            )
        )
        .scalars()
        .all()
    )
    ids = [application.id for application in applications]
    attempts = {
        attempt.application_id: attempt
        for attempt in (
            await db.execute(
                select(QuizAttempt)
                .join(Application, QuizAttempt.id == _latest_attempt_id())
                .where(Application.id.in_(ids))
            )
        )
        .scalars()
        .all()
    }
    interviews = {
        interview.application_id: interview
        for interview in (
            await db.execute(
                select(Interview).where(
                    Interview.application_id.in_(ids),
                    Interview.status != InterviewStatus.CANCELLED,
                )
            )
        )
        .scalars()
        .all()
    }
    return [
        LiveRow(
            application,
            attempt_view(attempts.get(application.id)),
            interview_view(interviews.get(application.id)),
        )
        for application in applications
    ]


async def waiting_ids(
    db: AsyncSession,
    company: Company,
    who: Who,
    *,
    job_id: uuid.UUID | None = None,
    now: datetime | None = None,
) -> frozenset[uuid.UUID]:
    """Live applications waiting on `who`, by the same rules as the board."""
    now = now or datetime.now(UTC)
    return frozenset(
        row.application.id
        for row in await _load_live(db, company)
        if (job_id is None or row.application.job_id == job_id)
        and waiting_on(
            row.application.stage,
            row.application.stage_changed_at,
            row.attempt_view,
            row.interview_view,
            now,
        ).who
        == who
    )


@dataclass(frozen=True)
class Movement:
    counts: list[int]  # events at or after each `since`, in the order given
    last_at: datetime  # newest event ever, not bounded by a window


async def _movement(
    db: AsyncSession,
    company: Company,
    job_ids: Sequence[uuid.UUID],
    since: Sequence[datetime],
) -> dict[uuid.UUID, Movement]:
    """Movement per job: stage.changed activity, new applications, quiz attempts
    completed. One count per `since` window, plus the all-time last event."""
    events = union_all(
        select(Application.job_id.label("job_id"), ActivityLog.created_at.label("at"))
        .join(Application, Application.id == ActivityLog.application_id)
        .where(
            ActivityLog.company_id == company.id,
            ActivityLog.type == STAGE_CHANGED,
            Application.job_id.in_(job_ids),
        ),
        select(Application.job_id, Application.created_at).where(
            Application.company_id == company.id, Application.job_id.in_(job_ids)
        ),
        select(Application.job_id, QuizAttempt.completed_at)
        .join(Application, Application.id == QuizAttempt.application_id)
        .where(
            QuizAttempt.company_id == company.id,
            QuizAttempt.completed_at.is_not(None),
            Application.job_id.in_(job_ids),
        ),
    ).subquery()
    rows = await db.execute(
        select(
            events.c.job_id,
            func.max(events.c.at),
            *[func.count().filter(events.c.at >= moment) for moment in since],
        ).group_by(events.c.job_id)
    )
    return {row[0]: Movement(list(row[2:]), row[1]) for row in rows.all()}


@dataclass(frozen=True)
class _Applications:
    new_since: int
    last_at: datetime | None


async def _application_dates(
    db: AsyncSession, company: Company, job_ids: Sequence[uuid.UUID], since: datetime
) -> dict[uuid.UUID, _Applications]:
    rows = await db.execute(
        select(
            Application.job_id,
            func.count().filter(Application.created_at >= since),
            func.max(Application.created_at),
        )
        .where(Application.company_id == company.id, Application.job_id.in_(job_ids))
        .group_by(Application.job_id)
    )
    return {job_id: _Applications(new, last) for job_id, new, last in rows.all()}


def _plural(n: int, one: str, many: str) -> str:
    return f"{n} {one if n == 1 else many}"


def _status(
    *,
    live: int,
    moved_in_limit: int,
    waiting_on_team: int,
    overdue: int,
    limit: int,
    last_application_at: datetime | None,
    now: datetime,
) -> tuple[BoardStatus, str]:
    """First match wins: empty, stalled, attention, on_track. The sentence is the chip tooltip."""
    window = _plural(limit, "day", "days")
    if live == 0:
        if last_application_at is None:
            return "empty", "No applications yet."
        n = _days_between(now, last_application_at)
        ago = "today" if n == 0 else f"{_plural(n, 'day', 'days')} ago"
        return "empty", f"No candidates in the pipeline. Last application {ago}."
    if moved_in_limit == 0:
        return (
            "stalled",
            f"No candidate moved in the last {window}. {waiting_on_team} waiting on you.",
        )
    if overdue >= 1:
        who = "candidate has" if overdue == 1 else "candidates have"
        return "attention", f"{overdue} {who} waited on you for more than {window}."
    return "on_track", f"Candidates moved in the last {window} and nobody is overdue."


_RANK: dict[str, int] = {"stalled": 0, "attention": 1, "on_track": 2, "empty": 3}


async def board(db: AsyncSession, company: Company, *, now: datetime | None = None) -> BoardOut:
    """Open roles: every published job plus closed jobs that still hold live candidates."""
    now = now or datetime.now(UTC)
    limit = stage_limit(company)
    rows = await _load_live(db, company)
    by_job: dict[uuid.UUID, list[LiveRow]] = defaultdict(list)
    jobs: dict[uuid.UUID, Job] = {}
    for row in rows:
        by_job[row.application.job_id].append(row)
        jobs[row.application.job_id] = row.application.job
    published = (
        (
            await db.execute(
                select(Job).where(Job.company_id == company.id, Job.status == JobStatus.PUBLISHED)
            )
        )
        .scalars()
        .all()
    )
    for job in published:
        jobs[job.id] = job

    job_ids = list(jobs)
    week_ago = now - timedelta(days=7)
    movement = await _movement(db, company, job_ids, [now - timedelta(days=limit), week_ago])
    dates = await _application_dates(db, company, job_ids, week_ago)

    out: list[BoardJob] = []
    for job_id, job in jobs.items():
        stages = {stage: 0 for stage in ("new", "screening", "interview", "offer")}
        waits: list[int] = []
        for row in by_job.get(job_id, []):
            application = row.application
            stages[application.stage.value] += 1
            waiting = waiting_on(
                application.stage,
                application.stage_changed_at,
                row.attempt_view,
                row.interview_view,
                now,
            )
            if waiting.who == "team":
                waits.append(_days_between(now, waiting.since))
        overdue = sum(1 for days in waits if days > limit)
        live = sum(stages.values())
        moved = movement.get(job_id)
        seen = dates.get(job_id)
        status, reason = _status(
            live=live,
            moved_in_limit=moved.counts[0] if moved else 0,
            waiting_on_team=len(waits),
            overdue=overdue,
            limit=limit,
            last_application_at=seen.last_at if seen else None,
            now=now,
        )
        days_open = None
        if job.published_at is not None:
            end = job.closed_at or now if job.status is JobStatus.CLOSED else now
            days_open = _days_between(end, job.published_at)
        out.append(
            BoardJob(
                job_id=job_id,
                title=job.title,
                job_status=job.status,
                status=status,
                live_by_stage=StageCounts(**stages),
                waiting_on_team=len(waits),
                longest_wait_days=max(waits) if waits else None,
                overdue=overdue,
                new_7d=seen.new_since if seen else 0,
                moved_7d=moved.counts[1] if moved else 0,
                days_open=days_open,
                last_movement_at=moved.last_at if moved else None,
                reason=reason,
            )
        )
    out.sort(key=lambda j: (_RANK[j.status], -j.overdue, j.title.lower(), str(j.job_id)))
    totals = BoardTotals(
        active_jobs=len(out),
        live=sum(sum(j.live_by_stage.model_dump().values()) for j in out),
        waiting_on_team=sum(j.waiting_on_team for j in out),
        overdue=sum(j.overdue for j in out),
        new_7d=sum(j.new_7d for j in out),
    )
    return BoardOut(stage_limit_days=limit, totals=totals, jobs=out)


async def stalled_jobs(db: AsyncSession, company: Company, *, now: datetime) -> list[BoardJob]:
    """The board rows with the stalled chip; the queue turns each into an item."""
    return [job for job in (await board(db, company, now=now)).jobs if job.status == "stalled"]
