"""Derived dashboard queue items (card D13): computed live from company
data, never stored. The only state is the per-user list of dismissed keys
on ``users.queue_dismissed``; keys whose item has resolved are pruned on
read so a condition that returns later shows up again.

Every query is company-scoped. Nothing here decides anything about a
candidate: the items are pointers into the admin screens where a human
reviews them.
"""

from datetime import UTC, datetime, timedelta
from urllib.parse import urlsplit

from sqlalchemy import ColumnElement, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased, selectinload

from app.core import urls
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
    UserRole,
)
from app.models.application import CLOSED_STAGES
from app.models.scorecard import Scorecard
from app.schemas.dashboard import QueueItem
from app.services import pipeline_signals
from app.services import scorecards as scorecard_service
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


def _open_scorecard_filters() -> list[ColumnElement[bool]]:
    return [
        Scorecard.submitted_at.is_(None),
        Scorecard.dismissed_at.is_(None),
        Scorecard.declined_at.is_(None),
    ]


def _relative(url: str) -> str:
    """Queue hrefs are app paths; ``urls`` builds the absolute form."""
    parts = urlsplit(url)
    return f"{parts.path}?{parts.query}" if parts.query else parts.path


async def _scorecards_waiting(
    db: AsyncSession, company: Company, *, now: datetime
) -> list[QueueItem]:
    """Staff view: scorecards a reviewer has left open for 3+ days."""
    reviewer = aliased(User)
    rows = (
        await db.execute(
            select(Scorecard, reviewer, Application.id, Candidate.name, Job.title)
            .join(Application, Application.id == Scorecard.application_id)
            .join(Candidate, Candidate.id == Application.candidate_id)
            .join(Job, Job.id == Application.job_id)
            .outerjoin(reviewer, reviewer.id == Scorecard.reviewer_user_id)
            .where(
                Scorecard.company_id == company.id,
                *_open_scorecard_filters(),
                Application.stage.not_in(CLOSED_STAGES),
                # loose bound; the service decides the exact UTC day boundary
                Scorecard.due_from < now - timedelta(days=2),
            )
            .order_by(Scorecard.due_from, Scorecard.id)
        )
    ).all()
    items: list[QueueItem] = []
    for row, reviewer_user, application_id, candidate_name, job_title in rows:
        days = scorecard_service.waiting_days(row, now=now)
        if days < scorecard_service.REMINDER_AFTER_DAYS:
            continue
        items.append(
            QueueItem(
                key=f"scorecard-waiting:{row.id}",
                kind="scorecard-waiting",
                title=(
                    f"Waiting on {scorecard_service.reviewer_label(reviewer_user)}: "
                    f"{candidate_name}"
                ),
                hint=f"{job_title} · {days} days",
                href=f"/admin/applicants?selected={application_id}",
                since=row.due_from,
            )
        )
    return items[:PER_SOURCE_LIMIT]


async def _scorecards_mine(
    db: AsyncSession, company: Company, user: User, *, now: datetime
) -> list[QueueItem]:
    """Every role: the scorecards this user has been asked to fill in."""
    requester = aliased(User)
    rows = (
        await db.execute(
            select(Scorecard, requester, Application.id, Candidate.name, Job.title)
            .join(Application, Application.id == Scorecard.application_id)
            .join(Candidate, Candidate.id == Application.candidate_id)
            .join(Job, Job.id == Application.job_id)
            .outerjoin(requester, requester.id == Scorecard.requested_by_user_id)
            .where(
                Scorecard.company_id == company.id,
                Scorecard.reviewer_user_id == user.id,
                *_open_scorecard_filters(),
                Application.stage.not_in(CLOSED_STAGES),
            )
            .order_by(Scorecard.requested_at, Scorecard.id)
            .limit(PER_SOURCE_LIMIT)
        )
    ).all()
    is_reviewer = scorecard_service.is_reviewer_role(user)
    items: list[QueueItem] = []
    for row, requester_user, application_id, candidate_name, job_title in rows:
        # no requester row: the booking path (candidate booked the interview)
        who = (
            "from your interview"
            if row.requested_by_user_id is None or requester_user is None
            else f"requested by {scorecard_service.reviewer_label(requester_user)}"
        )
        items.append(
            QueueItem(
                key=f"scorecard:{row.id}",
                kind="scorecard",
                title=f"Scorecard: {candidate_name}",
                hint=f"{job_title} · {who}",
                href=_relative(urls.scorecard_url(company, application_id, reviewer=is_reviewer)),
                since=row.requested_at,
            )
        )
    return items


async def _stalled_roles(db: AsyncSession, company: Company, *, now: datetime) -> list[QueueItem]:
    """Staff: one item per role the pipeline board marks stalled."""
    items: list[QueueItem] = []
    for job in await pipeline_signals.stalled_jobs(db, company, now=now):
        if job.last_movement_at is None:
            continue
        days = max(
            (now.astimezone(UTC).date() - job.last_movement_at.astimezone(UTC).date()).days, 0
        )
        if job.waiting_on_team:
            hint = f"{job.waiting_on_team} waiting on you"
        else:
            live = sum(job.live_by_stage.model_dump().values())
            hint = f"{live} candidate{'' if live == 1 else 's'}"
        items.append(
            QueueItem(
                key=f"role-stalled:{job.job_id}",
                kind="role-stalled",
                title=f"{job.title}: no movement for {days} {'day' if days == 1 else 'days'}",
                hint=hint,
                href=f"/admin/applicants?job={job.job_id}",
                since=job.last_movement_at,
            )
        )
    return items[:PER_SOURCE_LIMIT]


async def derived_items(
    db: AsyncSession, company: Company, user: User, *, now: datetime | None = None
) -> list[QueueItem]:
    """Every derived item whose condition currently holds, dismissals ignored."""
    now = now or datetime.now(UTC)
    items: list[QueueItem] = []
    if user.role in (UserRole.ADMIN, UserRole.MEMBER):
        items += await _jobs_without_quiz(db, company)
        items += await _open_integrity_flags(db, company)
        items += await _unbooked_interviews(db, company)
        items += await _scorecards_waiting(db, company, now=now)
        items += await _stalled_roles(db, company, now=now)
    return items + await _scorecards_mine(db, company, user, now=now)


async def visible_items(db: AsyncSession, company: Company, user: User) -> list[QueueItem]:
    """Derived items minus the user's dismissals. Dismissed keys that no
    longer match a live item are dropped from the user row, so the list
    stays bounded and a recurring condition is shown again."""
    items = await derived_items(db, company, user)
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
    live = {item.key for item in await derived_items(db, company, user)}
    if key not in live:
        return False
    dismissed = list(user.queue_dismissed or [])
    if key not in dismissed:
        dismissed.append(key)
        user.queue_dismissed = dismissed
        await db.commit()
    return True
