"""Derived dashboard queue items (card D13): computed live from company
data, never stored. The only state is the per-user list of dismissed keys
on ``users.queue_dismissed``; keys whose item has resolved are pruned on
read so a condition that returns later shows up again.

Every query is company-scoped. Nothing here decides anything about a
candidate: the items are pointers into the admin screens where a human
reviews them.
"""

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import (
    Application,
    AttemptStatus,
    Candidate,
    Company,
    Interview,
    InterviewStatus,
    Job,
    JobStatus,
    QuizAttempt,
    User,
)
from app.models.application import CLOSED_STAGES
from app.schemas.dashboard import QueueItem
from app.services.quiz import parse_quiz_config

PER_SOURCE_LIMIT = 20


async def _jobs_without_quiz(db: AsyncSession, company: Company) -> list[QueueItem]:
    jobs = (
        (
            await db.execute(
                select(Job)
                .where(Job.company_id == company.id, Job.status == JobStatus.PUBLISHED)
                .order_by(Job.created_at)
            )
        )
        .scalars()
        .all()
    )
    return [
        QueueItem(
            key=f"job-quiz:{job.id}",
            kind="job-quiz",
            title=f"Add a quiz to {job.title}",
            hint="Published without screening",
            href=f"/admin/jobs/{job.id}/edit",
            since=job.updated_at,
        )
        for job in jobs
        if not parse_quiz_config(job).enabled
    ][:PER_SOURCE_LIMIT]


async def _open_integrity_flags(db: AsyncSession, company: Company) -> list[QueueItem]:
    """Completed attempts with flags and no human review yet. A reissue
    marks the old attempt invalidated, so COMPLETED is always the latest."""
    rows = (
        await db.execute(
            select(QuizAttempt, Application.id, Candidate.name, Job.title)
            .join(Application, Application.id == QuizAttempt.application_id)
            .join(Candidate, Candidate.id == Application.candidate_id)
            .join(Job, Job.id == Application.job_id)
            .where(
                QuizAttempt.company_id == company.id,
                QuizAttempt.status == AttemptStatus.COMPLETED,
                func.jsonb_array_length(QuizAttempt.integrity["flags"]) > 0,
                ~QuizAttempt.integrity.has_key("review"),
                Application.stage.not_in(CLOSED_STAGES),
            )
            .order_by(QuizAttempt.completed_at)
            .limit(PER_SOURCE_LIMIT)
        )
    ).all()
    items: list[QueueItem] = []
    for attempt, application_id, candidate_name, job_title in rows:
        summaries = [
            str(flag.get("summary") or flag.get("code") or "")
            for flag in attempt.integrity.get("flags", [])
            if isinstance(flag, dict)
        ]
        items.append(
            QueueItem(
                key=f"integrity:{attempt.id}",
                kind="integrity",
                title=f"Review quiz flags: {candidate_name}",
                hint=" · ".join([job_title, *[s for s in summaries if s]]),
                href=f"/admin/applicants?selected={application_id}",
                since=attempt.completed_at,
            )
        )
    return items


async def _unbooked_interviews(db: AsyncSession, company: Company) -> list[QueueItem]:
    interviews = (
        (
            await db.execute(
                select(Interview)
                .join(Application, Application.id == Interview.application_id)
                .where(
                    Interview.company_id == company.id,
                    Interview.status == InterviewStatus.PENDING,
                    Application.stage.not_in(CLOSED_STAGES),
                )
                .options(
                    selectinload(Interview.application).selectinload(Application.candidate),
                    selectinload(Interview.application).selectinload(Application.job),
                )
                .order_by(Interview.created_at)
                .limit(PER_SOURCE_LIMIT)
            )
        )
        .scalars()
        .all()
    )
    return [
        QueueItem(
            key=f"unbooked:{iv.id}",
            kind="unbooked",
            title=f"Awaiting booking: {iv.application.candidate.name}",
            hint=f"{iv.application.job.title} · {iv.title}",
            href=f"/admin/applicants?selected={iv.application_id}",
            since=iv.created_at,
        )
        for iv in interviews
    ]


async def derived_items(db: AsyncSession, company: Company) -> list[QueueItem]:
    """Every derived item whose condition currently holds, dismissals ignored."""
    return (
        await _jobs_without_quiz(db, company)
        + await _open_integrity_flags(db, company)
        + await _unbooked_interviews(db, company)
    )


async def visible_items(db: AsyncSession, company: Company, user: User) -> list[QueueItem]:
    """Derived items minus the user's dismissals. Dismissed keys that no
    longer match a live item are dropped from the user row, so the list
    stays bounded and a recurring condition is shown again."""
    items = await derived_items(db, company)
    dismissed = list(user.queue_dismissed or [])
    if not dismissed:
        return items
    live = {item.key for item in items}
    still_relevant = [key for key in dismissed if key in live]
    if still_relevant != dismissed:
        user.queue_dismissed = still_relevant or None
        await db.commit()
    hidden = set(still_relevant)
    return [item for item in items if item.key not in hidden]


async def dismiss(db: AsyncSession, company: Company, user: User, key: str) -> bool:
    """Hide one live item for this user. False when ``key`` is not a current
    item (resolved already, or never this company's), so the list can only
    hold keys the server itself produced."""
    live = {item.key for item in await derived_items(db, company)}
    if key not in live:
        return False
    dismissed = list(user.queue_dismissed or [])
    if key not in dismissed:
        dismissed.append(key)
        user.queue_dismissed = dismissed
        await db.commit()
    return True
