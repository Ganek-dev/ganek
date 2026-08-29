"""Slot-generation logic; free/busy is faked at the google_calendar seam."""

from datetime import datetime, timedelta
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    Application,
    Candidate,
    Company,
    Interview,
    InterviewStatus,
    Job,
    User,
    UserRole,
)
from app.services import interviews as interviews_service
from tests.db import database_reachable

pytestmark = pytest.mark.skipif(
    not database_reachable(), reason="database not reachable (start postgres or use CI)"
)

BERLIN = ZoneInfo("Europe/Berlin")


async def _interviewer(db: AsyncSession) -> User:
    company = Company(slug=f"slot-{uuid4().hex[:8]}", name="Slot Co")
    db.add(company)
    await db.flush()
    user = User(
        company_id=company.id,
        email=f"dana-{uuid4().hex[:8]}@slot.dev",
        password_hash="x",
        role=UserRole.MEMBER,
    )
    db.add(user)
    await db.commit()
    return user


def _fake_freebusy(windows: list[tuple[datetime, datetime]]) -> object:
    async def freebusy(
        db: AsyncSession, user: User, start: datetime, end: datetime
    ) -> list[tuple[datetime, datetime]]:
        return windows

    return freebusy


async def _application_row(db: AsyncSession, user: User) -> Application:
    """The FK chain an interview needs: job + candidate + application."""
    job = Job(company_id=user.company_id, slug=f"job-{uuid4().hex[:8]}", title="Backend Dev")
    candidate = Candidate(
        company_id=user.company_id, email=f"cand-{uuid4().hex[:8]}@ganek-ci.dev", name="Marta"
    )
    db.add_all([job, candidate])
    await db.flush()
    application = Application(
        company_id=user.company_id,
        job_id=job.id,
        candidate_id=candidate.id,
        cv_object_key=f"cvs/{uuid4().hex}.pdf",
        cv_filename="cv.pdf",
        cv_size=1000,
    )
    db.add(application)
    await db.flush()
    return application


async def _booked_interview(
    db: AsyncSession, user: User, *, start: datetime, duration_minutes: int
) -> Interview:
    """A BOOKED interview occupying `start`."""
    application = await _application_row(db, user)
    interview = Interview(
        company_id=user.company_id,
        application_id=application.id,
        interviewer_user_id=user.id,
        duration_minutes=duration_minutes,
        timezone="Europe/Berlin",
        status=InterviewStatus.BOOKED,
        scheduled_start=start,
    )
    db.add(interview)
    await db.commit()
    return interview


async def _pending_interview(db: AsyncSession, user: User, *, duration_minutes: int) -> Interview:
    """An offered-but-unbooked interview, ready for the candidate to pick."""
    application = await _application_row(db, user)
    interview = Interview(
        company_id=user.company_id,
        application_id=application.id,
        interviewer_user_id=user.id,
        duration_minutes=duration_minutes,
        timezone="Europe/Berlin",
        status=InterviewStatus.PENDING,
    )
    db.add(interview)
    await db.commit()
    return interview


@pytest.mark.usefixtures("migrated_db")
async def test_slots_follow_default_availability(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    user = await _interviewer(db_session)
    monkeypatch.setattr(interviews_service.google_calendar, "freebusy", _fake_freebusy([]))
    slots = await interviews_service.generate_slots(
        db_session, user, duration_minutes=60, timezone="Europe/Berlin"
    )
    assert slots
    today = datetime.now(BERLIN).date()
    for slot in slots:
        assert slot.date() > today
        assert slot.weekday() < 5  # default = Mon-Fri
        assert slot.timetz().hour >= 9
        assert (slot + timedelta(minutes=60)).timetz().hour <= 17  # default ends 17:00
    assert (slots[-1].date() - today).days <= interviews_service.HORIZON_DAYS


@pytest.mark.usefixtures("migrated_db")
async def test_slots_respect_saved_windows_and_zone(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    user = await _interviewer(db_session)
    user.interview_availability = {
        "timezone": "Europe/Berlin",
        "days": {"tue": {"start": "10:00", "end": "12:00"}},
    }
    await db_session.commit()
    monkeypatch.setattr(interviews_service.google_calendar, "freebusy", _fake_freebusy([]))
    # fallback tz param deliberately different: saved zone must win
    slots = await interviews_service.generate_slots(
        db_session, user, duration_minutes=30, timezone="America/New_York"
    )
    assert slots
    for slot in slots:
        local = slot.astimezone(BERLIN)
        assert local.strftime("%a") == "Tue"
        assert local.hour in (10, 11)


@pytest.mark.usefixtures("migrated_db")
async def test_slots_exclude_ganek_booked_interviews(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Google freebusy lag must not reopen a slot ganek already booked."""
    user = await _interviewer(db_session)
    monkeypatch.setattr(interviews_service.google_calendar, "freebusy", _fake_freebusy([]))
    baseline = await interviews_service.generate_slots(
        db_session, user, duration_minutes=30, timezone="Europe/Berlin"
    )
    target = baseline[0]
    interview = await _booked_interview(db_session, user, start=target, duration_minutes=30)
    assert interview.status.value == "booked"
    slots = await interviews_service.generate_slots(
        db_session, user, duration_minutes=30, timezone="Europe/Berlin"
    )
    assert target not in slots
    assert len(slots) == len(baseline) - 1


@pytest.mark.usefixtures("migrated_db")
async def test_slots_avoid_busy_windows(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    user = await _interviewer(db_session)
    # block every morning 09:00-13:00 for the next 20 days
    busy: list[tuple[datetime, datetime]] = []
    day = datetime.now(BERLIN).date()
    for offset in range(1, 21):
        d = day + timedelta(days=offset)
        busy.append(
            (
                datetime(d.year, d.month, d.day, 9, 0, tzinfo=BERLIN),
                datetime(d.year, d.month, d.day, 13, 0, tzinfo=BERLIN),
            )
        )
    monkeypatch.setattr(interviews_service.google_calendar, "freebusy", _fake_freebusy(busy))
    slots = await interviews_service.generate_slots(
        db_session, user, duration_minutes=30, timezone="Europe/Berlin"
    )
    assert slots
    for slot in slots:
        assert slot.astimezone(BERLIN).hour >= 13


@pytest.mark.usefixtures("migrated_db")
async def test_slots_respect_one_hour_lead_time(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Spec §3 promises >=1h lead time. A saved window covering midnight
    means "tomorrow" can start within a minute of now — those near-term
    slots must still be excluded, not just anything before "now"."""
    user = await _interviewer(db_session)
    all_day_window = {"start": "00:00", "end": "23:30"}
    user.interview_availability = {
        "timezone": "Europe/Berlin",
        "days": dict.fromkeys(interviews_service.WEEKDAY_KEYS, all_day_window),
    }
    await db_session.commit()
    monkeypatch.setattr(interviews_service.google_calendar, "freebusy", _fake_freebusy([]))
    slots = await interviews_service.generate_slots(
        db_session, user, duration_minutes=30, timezone="Europe/Berlin"
    )
    assert slots
    now = datetime.now(BERLIN)
    today = now.date()
    for slot in slots:
        assert slot >= now + timedelta(hours=1)
        # still starts tomorrow, per existing behavior
        assert slot.astimezone(BERLIN).date() > today


@pytest.mark.usefixtures("migrated_db")
async def test_unknown_timezone_raises(db_session: AsyncSession) -> None:
    user = await _interviewer(db_session)
    with pytest.raises(ValueError):
        await interviews_service.generate_slots(
            db_session, user, duration_minutes=30, timezone="Mars/Olympus_Mons"
        )


@pytest.mark.usefixtures("migrated_db")
async def test_failed_booking_commit_compensates_the_created_event(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """If the DB commit dies after the Meet event was created, the event is
    best-effort deleted — otherwise the candidate holds a calendar invite
    for a booking Ganek never recorded (and the slot stays double-bookable)."""
    user = await _interviewer(db_session)
    monkeypatch.setattr(interviews_service.google_calendar, "freebusy", _fake_freebusy([]))
    baseline = await interviews_service.generate_slots(
        db_session, user, duration_minutes=30, timezone="Europe/Berlin"
    )
    target = baseline[0]
    pending = await _pending_interview(db_session, user, duration_minutes=30)
    pending_id = pending.id  # capture now: book()'s rollback expires the object
    interview = await interviews_service.get_by_id_public(db_session, pending_id)
    assert interview is not None

    deleted: list[str] = []

    async def fake_create(db: AsyncSession, u: User, **kwargs: object) -> tuple[str, str]:
        return "evt-doomed", "https://meet.google.com/xyz"

    async def fake_delete(db: AsyncSession, u: User, event_id: str) -> None:
        deleted.append(event_id)

    monkeypatch.setattr(interviews_service.google_calendar, "create_meet_event", fake_create)
    monkeypatch.setattr(interviews_service.google_calendar, "delete_event", fake_delete)

    async def failing_commit() -> None:
        raise RuntimeError("connection lost mid-commit")

    monkeypatch.setattr(db_session, "commit", failing_commit)
    with pytest.raises(RuntimeError, match="connection lost"):
        await interviews_service.book(db_session, interview, start=target)
    monkeypatch.undo()  # restore commit (and the fakes) before reusing the session

    assert deleted == ["evt-doomed"]
    fresh = await interviews_service.get_by_id_public(db_session, pending_id)
    assert fresh is not None
    assert fresh.status is InterviewStatus.PENDING  # the booking never landed
    assert fresh.google_event_id is None
