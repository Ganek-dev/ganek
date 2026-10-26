"""Dashboard aggregates. Read-only; every query is company-scoped."""

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import ColumnElement, case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    Application,
    ApplicationStage,
    AttemptStatus,
    Candidate,
    Company,
    Job,
    JobStatus,
    QuizAttempt,
)
from app.schemas.stats import (
    ApplicationCounts,
    JobCounts,
    JobStats,
    PerJobStats,
    QuizCounts,
    RecentApplication,
    StatsOverview,
    WeeklyPoint,
)
from app.services import applications as applications_service

WEEKS = 8
RECENT = 5


def _week_start(moment: datetime) -> datetime:
    monday = moment - timedelta(days=moment.weekday())
    return monday.replace(hour=0, minute=0, second=0, microsecond=0)


async def _job_counts(db: AsyncSession, company: Company) -> JobCounts:
    rows = (
        await db.execute(
            select(Job.status, func.count())
            .where(Job.company_id == company.id)
            .group_by(Job.status)
        )
    ).all()
    return JobCounts(**{status.value: count for status, count in rows})


async def _application_counts(db: AsyncSession, company: Company) -> ApplicationCounts:
    week_ago = datetime.now(UTC) - timedelta(days=7)
    row = (
        await db.execute(
            select(
                func.count(),
                func.count().filter(Application.stage == ApplicationStage.NEW),
                func.count().filter(Application.created_at >= week_ago),
            ).where(Application.company_id == company.id)
        )
    ).one()
    return ApplicationCounts(total=row[0], new=row[1], last_7_days=row[2])


SCORE_BUCKETS = 10  # 10-point-wide histogram buckets over 0–100


def _attempt_scope(company: Company, job_id: uuid.UUID | None) -> list[ColumnElement[bool]]:
    """Where-conditions for one company's attempts, narrowed to one job when
    asked (QuizAttempt has no job_id; the join rides Application)."""
    conditions: list[ColumnElement[bool]] = [
        QuizAttempt.company_id == company.id,
        # a re-issue invalidates the earlier attempt: audit history, not a stat
        QuizAttempt.status != AttemptStatus.INVALIDATED,
    ]
    if job_id is not None:
        conditions.append(Application.id == QuizAttempt.application_id)
        conditions.append(Application.job_id == job_id)
    return conditions


async def _quiz_counts(
    db: AsyncSession, company: Company, job_id: uuid.UUID | None = None
) -> QuizCounts:
    completed_filter = QuizAttempt.status == AttemptStatus.COMPLETED
    scope = _attempt_scope(company, job_id)
    row = (
        await db.execute(
            select(
                func.count(),
                func.count().filter(QuizAttempt.started_at.is_not(None)),
                func.count().filter(completed_filter),
                func.avg(QuizAttempt.score).filter(completed_filter),
                func.percentile_cont(0.5)
                .within_group(QuizAttempt.score.asc())
                .filter(completed_filter),
                func.extract(
                    "epoch",
                    func.avg(QuizAttempt.completed_at - QuizAttempt.started_at).filter(
                        completed_filter, QuizAttempt.started_at.is_not(None)
                    ),
                ),
            ).where(*scope)
        )
    ).one()
    total, started, completed, avg_score, median_score, avg_duration = row

    # histogram of completed scores (stored as 0–1 fractions); a perfect 1.0
    # folds into the top bucket
    bucket = func.least(func.width_bucket(QuizAttempt.score, 0, 1, SCORE_BUCKETS), SCORE_BUCKETS)
    bucket_rows = (
        await db.execute(
            select(bucket, func.count())
            .where(*scope, completed_filter, QuizAttempt.score.is_not(None))
            .group_by(bucket)
        )
    ).all()
    distribution = [0] * SCORE_BUCKETS
    for bucket_index, count in bucket_rows:
        if bucket_index is not None and 1 <= int(bucket_index) <= SCORE_BUCKETS:
            distribution[int(bucket_index) - 1] = count

    return QuizCounts(
        attempts_total=total,
        attempts_started=started,
        attempts_completed=completed,
        completion_rate=(completed / total) if total else None,
        avg_score=float(avg_score) if avg_score is not None else None,
        median_score=float(median_score) if median_score is not None else None,
        avg_duration_seconds=float(avg_duration) if avg_duration is not None else None,
        score_distribution=distribution,
    )


async def _per_job(db: AsyncSession, company: Company) -> list[PerJobStats]:
    new_case = case((Application.stage == ApplicationStage.NEW, 1))
    rows = (
        await db.execute(
            select(
                Job.id,
                Job.title,
                Job.status,
                func.count(Application.id),
                func.count(new_case),
            )
            .outerjoin(Application, Application.job_id == Job.id)
            .where(Job.company_id == company.id)
            .group_by(Job.id, Job.title, Job.status)
            .order_by(Job.created_at.desc())
        )
    ).all()
    return [
        PerJobStats(job_id=job_id, title=title, status=status, applications=apps, new=new)
        for job_id, title, status, apps, new in rows
    ]


async def _weekly(
    db: AsyncSession, company: Company, job_id: uuid.UUID | None = None
) -> list[WeeklyPoint]:
    now = datetime.now(UTC)
    start = _week_start(now) - timedelta(weeks=WEEKS - 1)
    bucket = func.date_trunc("week", Application.created_at)
    conditions = [Application.company_id == company.id, Application.created_at >= start]
    if job_id is not None:
        conditions.append(Application.job_id == job_id)
    rows = (
        await db.execute(select(bucket, func.count()).where(*conditions).group_by(bucket))
    ).all()
    counts = {moment.date(): count for moment, count in rows}
    return [
        WeeklyPoint(
            week_start=(start + timedelta(weeks=i)).date(),
            count=counts.get((start + timedelta(weeks=i)).date(), 0),
        )
        for i in range(WEEKS)
    ]


async def _recent(db: AsyncSession, company: Company) -> list[RecentApplication]:
    rows = (
        await db.execute(
            select(
                Application.id,
                Candidate.name,
                Application.job_id,
                Job.title,
                Application.stage,
                QuizAttempt.score,
                Application.created_at,
            )
            .join(Candidate, Candidate.id == Application.candidate_id)
            .join(Job, Job.id == Application.job_id)
            .outerjoin(QuizAttempt, QuizAttempt.application_id == Application.id)
            .where(Application.company_id == company.id)
            .order_by(Application.created_at.desc())
            .limit(RECENT)
        )
    ).all()
    return [
        RecentApplication(
            id=app_id,
            candidate_name=name,
            job_id=job_id,
            job_title=title,
            stage=stage,
            quiz_score=score,
            created_at=created_at,
        )
        for app_id, name, job_id, title, stage, score, created_at in rows
    ]


async def overview(db: AsyncSession, company: Company) -> StatsOverview:
    return StatsOverview(
        jobs=await _job_counts(db, company),
        applications=await _application_counts(db, company),
        quiz=await _quiz_counts(db, company),
        per_job=await _per_job(db, company),
        weekly=await _weekly(db, company),
        recent=await _recent(db, company),
    )


async def job_stats(db: AsyncSession, company: Company, job: Job) -> JobStats:
    """Overview numbers for one job of this company (the caller resolved the
    job through the tenancy dependency)."""
    now = datetime.now(UTC)
    row = (
        await db.execute(
            select(
                func.count(),
                func.count().filter(Application.stage == ApplicationStage.NEW),
                func.count().filter(Application.created_at >= now - timedelta(days=7)),
                func.count().filter(Application.created_at >= now - timedelta(days=30)),
            ).where(Application.company_id == company.id, Application.job_id == job.id)
        )
    ).one()
    if job.published_at is None:
        days_open = None
    elif job.status is JobStatus.CLOSED:
        # jobs closed before migration 0033 carry no closed_at: show "-"
        # rather than a number that grows every day
        days_open = None if job.closed_at is None else (job.closed_at - job.published_at).days
    else:
        days_open = (now - job.published_at).days
    return JobStats(
        applications=ApplicationCounts(total=row[0], new=row[1], last_7_days=row[2]),
        last_30_days=row[3],
        by_stage=await applications_service.count_by_stage(db, company, job_id=job.id),
        quiz=await _quiz_counts(db, company, job_id=job.id),
        weekly=await _weekly(db, company, job_id=job.id),
        days_open=days_open,
    )
