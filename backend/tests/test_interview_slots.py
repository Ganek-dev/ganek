"""Slot-generation logic: saved availability minus Ganek's own bookings."""

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
async def test_slots_follow_default_availability(db_session: AsyncSession) -> None:
    user = await _interviewer(db_session)
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
async def test_slots_respect_saved_windows_and_zone(db_session: AsyncSession) -> None:
    user = await _interviewer(db_session)
    user.interview_availability = {
        "timezone": "Europe/Berlin",
        "days": {"tue": {"start": "10:00", "end": "12:00"}},
    }
    await db_session.commit()
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
async def test_slots_exclude_ganek_booked_interviews(db_session: AsyncSession) -> None:
    """A slot Ganek already booked for this interviewer is not offered again."""
    user = await _interviewer(db_session)
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
async def test_slots_respect_one_hour_lead_time(db_session: AsyncSession) -> None:
    """Spec §3 promises >=1h lead time. A saved window covering midnight
    means "tomorrow" can start within a minute of now - those near-term
    slots must still be excluded, not just anything before "now"."""
    user = await _interviewer(db_session)
    all_day_window = {"start": "00:00", "end": "23:30"}
    user.interview_availability = {
        "timezone": "Europe/Berlin",
        "days": dict.fromkeys(interviews_service.WEEKDAY_KEYS, all_day_window),
    }
    await db_session.commit()
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
async def test_slots_ignore_nothing_but_own_bookings(db_session: AsyncSession) -> None:
    """A PENDING request and a CANCELLED booking leave the slot set alone;
    only a BOOKED interview blocks its window."""
    user = await _interviewer(db_session)
    baseline = await interviews_service.generate_slots(
        db_session, user, duration_minutes=30, timezone="Europe/Berlin"
    )
    await _pending_interview(db_session, user, duration_minutes=30)
    cancelled = await _booked_interview(db_session, user, start=baseline[1], duration_minutes=30)
    cancelled.status = InterviewStatus.CANCELLED
    await db_session.commit()
    slots = await interviews_service.generate_slots(
        db_session, user, duration_minutes=30, timezone="Europe/Berlin"
    )
    assert slots == baseline
