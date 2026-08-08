"""Slot-generation logic; free/busy is faked at the google_calendar seam."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Company, User, UserRole
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


@pytest.mark.usefixtures("migrated_db")
async def test_slots_skip_weekends_and_respect_cap(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    user = await _interviewer(db_session)
    monkeypatch.setattr(interviews_service.google_calendar, "freebusy", _fake_freebusy([]))
    slots = await interviews_service.generate_slots(
        db_session, user, duration_minutes=45, timezone="Europe/Berlin"
    )
    assert slots, "an empty calendar must yield slots"
    assert all(slot.weekday() < 5 for slot in slots)
    per_day: dict[str, int] = {}
    for slot in slots:
        per_day[slot.date().isoformat()] = per_day.get(slot.date().isoformat(), 0) + 1
    assert set(per_day.values()) == {4}  # cap reached every business day
    assert len(per_day) == 10


@pytest.mark.usefixtures("migrated_db")
async def test_slots_start_tomorrow_within_working_hours(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    user = await _interviewer(db_session)
    monkeypatch.setattr(interviews_service.google_calendar, "freebusy", _fake_freebusy([]))
    slots = await interviews_service.generate_slots(
        db_session, user, duration_minutes=60, timezone="Europe/Berlin"
    )
    today = datetime.now(BERLIN).date()
    for slot in slots:
        assert slot.date() > today
        assert slot.timetz().hour >= 9
        # 60-minute interview must END by 18:00
        assert (slot + timedelta(minutes=60)).timetz().hour <= 18


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
async def test_unknown_timezone_raises(db_session: AsyncSession) -> None:
    user = await _interviewer(db_session)
    with pytest.raises(ValueError):
        await interviews_service.generate_slots(
            db_session, user, duration_minutes=30, timezone="Mars/Olympus_Mons"
        )


@pytest.mark.usefixtures("migrated_db")
async def test_offered_slots_freeze_as_utc(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    slot = datetime(2026, 8, 12, 14, 0, tzinfo=BERLIN)
    assert slot.astimezone(UTC).isoformat() == "2026-08-12T12:00:00+00:00"
