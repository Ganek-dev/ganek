from datetime import UTC, datetime, timedelta

from app.models.application import ApplicationStage
from app.models.interview import InterviewStatus
from app.models.quiz import AttemptStatus
from app.services.pipeline_signals import (
    AttemptView,
    InterviewView,
    Waiting,
    interview_view,
    is_overdue,
    waiting_on,
)

NOW = datetime(2026, 11, 1, 12, 0, tzinfo=UTC)
CHANGED = NOW - timedelta(days=3)


def _attempt(
    status: AttemptStatus,
    *,
    created: datetime = NOW - timedelta(days=2),
    completed: datetime | None = None,
    expires: datetime = NOW + timedelta(days=5),
) -> AttemptView:
    return AttemptView(status, created, completed, expires)


def _interview(
    status: InterviewStatus,
    *,
    created: datetime = NOW - timedelta(days=4),
    start: datetime | None = None,
    minutes: int = 60,
) -> InterviewView:
    return InterviewView(status, created, start, minutes)


def _wait(stage, attempt=None, interview=None):
    return waiting_on(stage, CHANGED, attempt, interview, NOW)


def test_pending_interview_at_screening_is_candidate_since_interview_created():
    iv = _interview(InterviewStatus.PENDING)
    assert _wait(ApplicationStage.SCREENING, interview=iv) == Waiting("candidate", iv.created_at)


def test_booked_future_interview_at_new_is_candidate():
    iv = _interview(InterviewStatus.BOOKED, start=NOW + timedelta(hours=1))
    assert _wait(ApplicationStage.NEW, interview=iv) == Waiting("candidate", iv.created_at)


def test_booked_interview_still_running_is_candidate():
    iv = _interview(InterviewStatus.BOOKED, start=NOW - timedelta(minutes=30), minutes=60)
    assert _wait(ApplicationStage.INTERVIEW, interview=iv).who == "candidate"


def test_held_interview_at_screening_is_team_since_end():
    start = NOW - timedelta(days=2)
    iv = _interview(InterviewStatus.BOOKED, start=start, minutes=45)
    assert _wait(ApplicationStage.SCREENING, interview=iv) == Waiting(
        "team", start + timedelta(minutes=45)
    )


def test_held_interview_then_moved_to_offer_is_candidate_since_stage_changed():
    iv = _interview(InterviewStatus.BOOKED, start=NOW - timedelta(days=5), minutes=60)
    assert _wait(ApplicationStage.OFFER, interview=iv) == Waiting("candidate", CHANGED)


def test_held_interview_then_moved_to_screening_is_team_since_stage_changed():
    iv = _interview(InterviewStatus.BOOKED, start=NOW - timedelta(days=5), minutes=60)
    assert _wait(ApplicationStage.SCREENING, interview=iv) == Waiting("team", CHANGED)


def test_cancelled_interview_is_ignored_team_since_stage_changed():
    assert interview_view(None) is None
    # a cancelled row maps to None, so the stage row applies
    assert _wait(ApplicationStage.INTERVIEW, interview=None) == Waiting("team", CHANGED)


def test_new_pending_attempt_not_expired_is_candidate_since_attempt_created():
    a = _attempt(AttemptStatus.PENDING)
    assert _wait(ApplicationStage.NEW, a) == Waiting("candidate", a.created_at)


def test_new_in_progress_is_candidate():
    a = _attempt(AttemptStatus.IN_PROGRESS)
    assert _wait(ApplicationStage.NEW, a) == Waiting("candidate", a.created_at)


def test_new_completed_is_team_since_completed_at():
    done = NOW - timedelta(days=1)
    a = _attempt(AttemptStatus.COMPLETED, completed=done)
    assert _wait(ApplicationStage.NEW, a) == Waiting("team", done)


def test_new_expired_status_is_team_since_expires_at():
    exp = NOW - timedelta(days=1)
    a = _attempt(AttemptStatus.EXPIRED, expires=exp)
    assert _wait(ApplicationStage.NEW, a) == Waiting("team", exp)


def test_new_pending_past_expiry_is_team_since_expires_at():
    exp = NOW - timedelta(hours=2)
    a = _attempt(AttemptStatus.PENDING, expires=exp)
    assert _wait(ApplicationStage.NEW, a) == Waiting("team", exp)


def test_new_invalidated_or_no_attempt_is_team_since_stage_changed():
    assert _wait(ApplicationStage.NEW) == Waiting("team", CHANGED)
    a = _attempt(AttemptStatus.INVALIDATED)
    assert _wait(ApplicationStage.NEW, a) == Waiting("team", CHANGED)


def test_screening_is_team():
    assert _wait(ApplicationStage.SCREENING) == Waiting("team", CHANGED)


def test_interview_without_interview_row_is_team():
    assert _wait(ApplicationStage.INTERVIEW) == Waiting("team", CHANGED)


def test_offer_is_candidate():
    assert _wait(ApplicationStage.OFFER) == Waiting("candidate", CHANGED)


def test_overdue_boundary():
    team = lambda days: Waiting("team", NOW - timedelta(days=days))  # noqa: E731
    assert is_overdue(team(7), 7, NOW) is False
    assert is_overdue(team(8), 7, NOW) is True
    assert is_overdue(Waiting("candidate", NOW - timedelta(days=30)), 7, NOW) is False


def test_overdue_uses_utc_calendar_days_not_elapsed_hours():
    since = datetime(2026, 11, 1, 23, 50, tzinfo=UTC)
    now = datetime(2026, 11, 9, 0, 10, tzinfo=UTC)
    assert (now - since).days == 7  # elapsed-time arithmetic would say not overdue
    assert is_overdue(Waiting("team", since), 7, now) is True  # 8 calendar days
    assert is_overdue(Waiting("team", since), 8, now) is False
