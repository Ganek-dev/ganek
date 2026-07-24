"""Dashboard aggregates. Read-only; every query is company-scoped."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    Application,
    ApplicationStage,
    AttemptStatus,
    Candidate,
    Company,
    Job,
    QuizAttempt,
)
from app.schemas.stats import (
    ApplicationCounts,
    JobCounts,
    PerJobStats,
    QuizCounts,
    RecentApplication,
    StatsOverview,
    WeeklyPoint,
)

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


async def _quiz_counts(db: AsyncSession, company: Company) -> QuizCounts:
    row = (
        await db.execute(
            select(
                func.count(),
                func.count().filter(QuizAttempt.status == AttemptStatus.COMPLETED),
                func.avg(QuizAttempt.score).filter(QuizAttempt.status == AttemptStatus.COMPLETED),
            ).where(QuizAttempt.company_id == company.id)
        )
    ).one()
    total, completed, avg_score = row
    return QuizCounts(
        attempts_total=total,
        attempts_completed=completed,
        completion_rate=(completed / total) if total else None,
        avg_score=float(avg_score) if avg_score is not None else None,
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


async def _weekly(db: AsyncSession, company: Company) -> list[WeeklyPoint]:
    now = datetime.now(UTC)
    start = _week_start(now) - timedelta(weeks=WEEKS - 1)
    bucket = func.date_trunc("week", Application.created_at)
    rows = (
        await db.execute(
            select(bucket, func.count())
            .where(Application.company_id == company.id, Application.created_at >= start)
            .group_by(bucket)
        )
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
