"""Per-application timeline (board card "Candidate timeline").

One chronological trail merged from the three sources the product already
writes: ``activity_log`` (who did what), ``email_outbox`` (what went out and
whether it arrived) and ``quiz_attempts`` (invited, started, completed,
expired). Columns are the truth where they exist; the activity rows that
duplicate a column (``application.received``, ``quiz.finished``) are skipped
so nothing shows twice and tenants that predate a writer still get a trail.
Read-only: nothing here writes a row.
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ActivityLog, Application, AttemptStatus, Company, EmailOutbox, QuizAttempt
from app.services import activity

APPLIED = "applied"
QUIZ_INVITED = "quiz.invited"
QUIZ_STARTED = "quiz.started"
QUIZ_COMPLETED = "quiz.completed"
QUIZ_EXPIRED = "quiz.expired"
EMAIL = "email"

# facts a column already carries with more detail
_SKIPPED_ACTIVITY = frozenset({activity.APPLICATION_RECEIVED, activity.QUIZ_FINISHED})


@dataclass(frozen=True)
class TimelineEvent:
    id: str
    kind: str
    at: datetime
    actor_label: str | None = None
    actor_email: str | None = None
    payload: dict[str, object] = field(default_factory=dict)


def _attempt_events(attempts: list[QuizAttempt], *, now: datetime) -> list[TimelineEvent]:
    events: list[TimelineEvent] = []
    for index, attempt in enumerate(attempts):
        key = str(attempt.id)
        if index == 0:
            # later attempts are explained by their quiz.reissued row
            events.append(
                TimelineEvent(id=f"invited-{key}", kind=QUIZ_INVITED, at=attempt.created_at)
            )
        if attempt.started_at is not None:
            events.append(
                TimelineEvent(id=f"started-{key}", kind=QUIZ_STARTED, at=attempt.started_at)
            )
        if attempt.completed_at is not None:
            events.append(
                TimelineEvent(
                    id=f"completed-{key}",
                    kind=QUIZ_COMPLETED,
                    at=attempt.completed_at,
                    payload={"score": attempt.score},
                )
            )
        # the column only flips when the candidate opens a dead link, so a
        # pending attempt past its window counts as expired (same rule as
        # the list filter); a superseded attempt is history, not an expiry
        lapsed = attempt.status is AttemptStatus.PENDING and attempt.expires_at < now
        if attempt.status is AttemptStatus.EXPIRED or lapsed:
            events.append(
                TimelineEvent(id=f"expired-{key}", kind=QUIZ_EXPIRED, at=attempt.expires_at)
            )
    return events


def _email_event(row: EmailOutbox) -> TimelineEvent:
    return TimelineEvent(
        id=f"email-{row.id}",
        kind=EMAIL,
        at=row.sent_at or row.created_at,
        payload={
            "template": row.kind,
            "status": row.status.value,
            "attempts": row.attempts,
            "last_error": row.last_error,
        },
    )


def _activity_event(row: ActivityLog) -> TimelineEvent:
    actor = row.actor
    return TimelineEvent(
        id=f"activity-{row.id}",
        kind=row.type,
        at=row.created_at,
        actor_label=actor.display_label if actor is not None else None,
        actor_email=actor.email if actor is not None else None,
        payload=dict(row.payload),
    )


async def list_events(
    db: AsyncSession, company: Company, application: Application
) -> list[TimelineEvent]:
    """Everything that happened to this application, newest first."""
    scope = (QuizAttempt.company_id == company.id, QuizAttempt.application_id == application.id)
    attempts = list(
        (
            await db.execute(
                select(QuizAttempt).where(*scope).order_by(QuizAttempt.created_at, QuizAttempt.id)
            )
        )
        .scalars()
        .all()
    )
    emails = (
        (
            await db.execute(
                select(EmailOutbox).where(
                    EmailOutbox.company_id == company.id,
                    EmailOutbox.application_id == application.id,
                )
            )
        )
        .scalars()
        .all()
    )
    rows = (
        (
            await db.execute(
                select(ActivityLog).where(
                    ActivityLog.company_id == company.id,
                    ActivityLog.application_id == application.id,
                    ActivityLog.type.not_in(_SKIPPED_ACTIVITY),
                )
            )
        )
        .scalars()
        .all()
    )
    events = [
        TimelineEvent(
            id=f"applied-{application.id}",
            kind=APPLIED,
            at=application.created_at,
            payload={"source": application.source},
        ),
        *_attempt_events(attempts, now=datetime.now(UTC)),
        *(_email_event(row) for row in emails),
        *(_activity_event(row) for row in rows),
    ]
    events.sort(key=lambda event: (event.at, event.id), reverse=True)
    return events
