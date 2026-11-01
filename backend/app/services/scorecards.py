"""Interview scorecards (spec: SCORECARDS_SPEC 3.2, 4.3, 4.4, 4.7).

The row is the request and the answer. State is derived from the three
timestamps, never stored. Visualization only: nothing here gates a candidate.

Functions flush but do not commit, except ``request`` with ``notify=True``,
which always commits (row, activity and outbox row together; in demo mode
``queue_email`` drops the mail without committing, so ``request`` does).
"""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Literal

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import urls
from app.models import Application, Candidate, Company, Interview, Job, User
from app.models.application import CLOSED_STAGES
from app.models.scorecard import Recommendation, Scorecard
from app.services import activity
from app.services import outbox as outbox_service

REMINDER_AFTER_DAYS = 3
EDIT_WINDOW = timedelta(hours=24)

State = Literal["open", "submitted", "dismissed", "declined"]


class AlreadyOpenError(Exception):
    """The reviewer already holds an open (or submitted) request."""


class NotOpenError(Exception):
    pass


class EditWindowClosedError(Exception):
    pass


class SelfRequestError(Exception):
    """Nobody requests a scorecard from themselves."""


def state_of(row: Scorecard) -> State:
    if row.submitted_at is not None:
        return "submitted"
    if row.dismissed_at is not None:
        return "dismissed"
    if row.declined_at is not None:
        return "declined"
    return "open"


def waiting_days(row: Scorecard, *, now: datetime) -> int:
    """Whole UTC calendar days since the clock started, floor 0."""
    delta = now.astimezone(UTC).date() - row.due_from.astimezone(UTC).date()
    return max(delta.days, 0)


def reviewer_label(user: User | None) -> str:
    return "Former teammate" if user is None else user.display_label


def _is_reviewer_role(user: User) -> bool:
    # UserRole.REVIEWER lands with the reviewer role; compare by value until then
    return str(user.role) == "reviewer"


async def request(
    db: AsyncSession,
    *,
    application: Application,
    reviewer: User,
    requested_by: User | None,
    interview_id: uuid.UUID | None = None,
    due_from: datetime | None = None,
    notify: bool = True,
    now: datetime | None = None,
) -> Scorecard:
    """Create the request, or reopen a declined or dismissed one."""
    now = now or datetime.now(UTC)
    if requested_by is not None and requested_by.id == reviewer.id:
        raise SelfRequestError
    if reviewer.company_id != application.company_id:
        raise ValueError("reviewer is not in the application's company")
    job = (
        await db.execute(
            select(Job).where(
                Job.id == application.job_id, Job.company_id == application.company_id
            )
        )
    ).scalar_one()
    snapshot = [dict(c) for c in job.scorecard_template or []]
    row = (
        await db.execute(
            select(Scorecard).where(
                Scorecard.company_id == application.company_id,
                Scorecard.application_id == application.id,
                Scorecard.reviewer_user_id == reviewer.id,
            )
        )
    ).scalar_one_or_none()
    if row is not None and state_of(row) in ("open", "submitted"):
        raise AlreadyOpenError
    created: bool
    if row is None:
        row = Scorecard(
            company_id=application.company_id,
            application_id=application.id,
            job_id=job.id,
            reviewer_user_id=reviewer.id,
        )
        created = True
    else:
        created = False
    row.requested_by_user_id = requested_by.id if requested_by else None
    row.interview_id = interview_id
    row.requested_at = now
    row.due_from = due_from or now
    row.reminded_at = None
    row.submitted_at = None
    row.dismissed_at = None
    row.dismissed_by_user_id = None
    row.declined_at = None
    row.criteria_snapshot = snapshot
    row.ratings = {}
    row.recommendation = None
    row.comment = None
    if created:
        # a concurrent first request trips the partial unique index; answer it
        # like the sequential duplicate instead of a 500
        try:
            async with db.begin_nested():
                db.add(row)
                await db.flush()
        except IntegrityError:
            raise AlreadyOpenError from None
    activity.record(
        db,
        company_id=application.company_id,
        type=activity.SCORECARD_REQUESTED,
        actor_user_id=requested_by.id if requested_by else None,
        application_id=application.id,
        payload={"reviewer_label": reviewer_label(reviewer)},
    )
    await db.flush()
    if notify:
        company = await db.get(Company, application.company_id)
        candidate = await db.get(Candidate, application.candidate_id)
        assert company is not None and candidate is not None
        await outbox_service.queue_email(
            db,
            kind="scorecard_request",
            company_id=company.id,
            application_id=application.id,
            to=reviewer.email,
            ref=str(row.id),
            company_name=company.name,
            requester_label=reviewer_label(requested_by) if requested_by else company.name,
            candidate_name=candidate.name,
            job_title=job.title,
            url=urls.scorecard_url(company, application.id, reviewer=_is_reviewer_role(reviewer)),
            brand_primary=(company.theme or {}).get("primary_color"),
        )
        await db.commit()  # queue_email skips its own commit in demo mode
    return row


async def submit(
    db: AsyncSession,
    row: Scorecard,
    *,
    ratings: dict[str, int],
    recommendation: Recommendation,
    comment: str | None,
    now: datetime | None = None,
) -> Scorecard:
    now = now or datetime.now(UTC)
    state = state_of(row)
    if state == "submitted":
        assert row.submitted_at is not None
        if now - row.submitted_at > EDIT_WINDOW:
            raise EditWindowClosedError
    elif state != "open":
        raise NotOpenError
    known = {str(c["id"]) for c in row.criteria_snapshot}
    for criterion_id, value in ratings.items():
        if criterion_id not in known:
            raise ValueError(f"unknown criterion {criterion_id!r}")
        if isinstance(value, bool) or not 1 <= value <= 4:
            raise ValueError("ratings are 1 to 4")
    first = row.submitted_at is None
    row.ratings = dict(ratings)
    row.recommendation = recommendation
    row.comment = comment
    if first:
        row.submitted_at = now
        activity.record(
            db,
            company_id=row.company_id,
            type=activity.SCORECARD_SUBMITTED,
            actor_user_id=row.reviewer_user_id,
            application_id=row.application_id,
            payload={"reviewer_label": reviewer_label(row.reviewer)},
        )
    row.updated_at = now
    await db.flush()
    return row


async def decline(db: AsyncSession, row: Scorecard, *, now: datetime | None = None) -> None:
    if state_of(row) != "open":
        raise NotOpenError
    row.declined_at = now or datetime.now(UTC)
    activity.record(
        db,
        company_id=row.company_id,
        type=activity.SCORECARD_DECLINED,
        actor_user_id=row.reviewer_user_id,
        application_id=row.application_id,
        payload={"reviewer_label": reviewer_label(row.reviewer)},
    )
    await db.flush()


async def dismiss(
    db: AsyncSession,
    row: Scorecard,
    *,
    actor_user_id: uuid.UUID | None,
    now: datetime | None = None,
) -> None:
    if state_of(row) != "open":
        raise NotOpenError
    row.dismissed_at = now or datetime.now(UTC)
    row.dismissed_by_user_id = actor_user_id
    activity.record(
        db,
        company_id=row.company_id,
        type=activity.SCORECARD_DISMISSED,
        actor_user_id=actor_user_id,
        application_id=row.application_id,
        payload={"reviewer_label": reviewer_label(row.reviewer)},
    )
    await db.flush()


async def list_for_application(
    db: AsyncSession, *, company_id: uuid.UUID, application_id: uuid.UUID
) -> list[Scorecard]:
    result = await db.execute(
        select(Scorecard)
        .where(Scorecard.company_id == company_id, Scorecard.application_id == application_id)
        .order_by(Scorecard.requested_at, Scorecard.id)
    )
    return list(result.scalars())


async def get_mine(db: AsyncSession, *, user: User, application_id: uuid.UUID) -> Scorecard | None:
    return (
        await db.execute(
            select(Scorecard).where(
                Scorecard.company_id == user.company_id,
                Scorecard.application_id == application_id,
                Scorecard.reviewer_user_id == user.id,
            )
        )
    ).scalar_one_or_none()


async def list_mine(
    db: AsyncSession, *, user: User, state: Literal["open", "all"]
) -> list[Scorecard]:
    stmt = select(Scorecard).where(
        Scorecard.company_id == user.company_id, Scorecard.reviewer_user_id == user.id
    )
    if state == "open":
        stmt = stmt.where(
            Scorecard.submitted_at.is_(None),
            Scorecard.dismissed_at.is_(None),
            Scorecard.declined_at.is_(None),
        )
    else:
        stmt = stmt.where(Scorecard.dismissed_at.is_(None))
    result = await db.execute(stmt.order_by(Scorecard.due_from.desc(), Scorecard.id))
    return list(result.scalars())


async def _open_rows(db: AsyncSession, *conditions: object) -> list[Scorecard]:
    result = await db.execute(
        select(Scorecard).where(
            Scorecard.submitted_at.is_(None),
            Scorecard.dismissed_at.is_(None),
            Scorecard.declined_at.is_(None),
            *conditions,  # type: ignore[arg-type]
        )
    )
    return list(result.scalars())


async def dismiss_for_interview(
    db: AsyncSession, interview: Interview, *, actor_user_id: uuid.UUID | None
) -> None:
    """The interview was cancelled: withdraw the request it created."""
    for row in await _open_rows(
        db,
        Scorecard.company_id == interview.company_id,
        Scorecard.interview_id == interview.id,
    ):
        await dismiss(db, row, actor_user_id=actor_user_id)


async def dismiss_open_for_reviewer(
    db: AsyncSession, user: User, *, actor_user_id: uuid.UUID | None
) -> int:
    rows = await _open_rows(
        db, Scorecard.company_id == user.company_id, Scorecard.reviewer_user_id == user.id
    )
    for row in rows:
        await dismiss(db, row, actor_user_id=actor_user_id)
    return len(rows)


async def due_for_reminder(db: AsyncSession, *, now: datetime) -> list[Scorecard]:
    """Open, never reminded, waiting at least REMINDER_AFTER_DAYS, application
    still live and reviewer still active."""
    result = await db.execute(
        select(Scorecard)
        .join(Application, Application.id == Scorecard.application_id)
        .join(User, User.id == Scorecard.reviewer_user_id)
        .where(
            Scorecard.submitted_at.is_(None),
            Scorecard.dismissed_at.is_(None),
            Scorecard.declined_at.is_(None),
            Scorecard.reminded_at.is_(None),
            Scorecard.due_from <= now - timedelta(days=REMINDER_AFTER_DAYS),
            Application.company_id == Scorecard.company_id,
            Application.stage.not_in(CLOSED_STAGES),
            User.company_id == Scorecard.company_id,
            User.is_active.is_(True),
        )
        .order_by(Scorecard.due_from)
    )
    return list(result.scalars())


async def mark_reminded(db: AsyncSession, rows: list[Scorecard], *, now: datetime) -> None:
    for row in rows:
        row.reminded_at = now
    await db.flush()
