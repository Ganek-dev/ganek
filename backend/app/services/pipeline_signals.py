"""Pipeline signals: the workspace stage limit (stalled-candidate cue).

The setting reader and the pure waiting-on-whom rules; the signal queries build on them.
"""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal

from app.models.application import ApplicationStage
from app.models.company import Company
from app.models.interview import Interview, InterviewStatus
from app.models.quiz import AttemptStatus, QuizAttempt

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
