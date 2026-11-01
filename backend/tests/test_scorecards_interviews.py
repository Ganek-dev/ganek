"""Interview hooks for scorecards (spec 4.3): book requests, reschedule
follows, cancels withdraw."""

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ActivityLog, Interview
from app.models.scorecard import Scorecard
from app.services import interviews as interviews_service
from app.services import scorecards as svc
from tests.db import database_reachable
from tests.test_scorecards_service import Env, _env, mails  # noqa: F401

pytestmark = pytest.mark.skipif(
    not database_reachable(), reason="database not reachable (start postgres or use CI)"
)


async def _interview(db: AsyncSession, env: Env) -> Interview:
    return await interviews_service.create_interview(
        db,
        env.company,
        env.app,
        interviewer=env.admin,
        title="Hiring manager interview",
        description="",
        duration_minutes=45,
        timezone="Europe/Berlin",
    )


async def _slots(db: AsyncSession, env: Env) -> list[datetime]:
    return await interviews_service.generate_slots(
        db, env.admin, duration_minutes=45, timezone="Europe/Berlin"
    )


async def _booked(db: AsyncSession, env: Env) -> tuple[Interview, list[datetime]]:
    interview = await _interview(db, env)
    slots = await _slots(db, env)
    await interviews_service.book(db, interview, start=slots[0])
    return interview, slots


async def _rows(db: AsyncSession, env: Env) -> list[Scorecard]:
    await db.rollback()  # see only what was committed
    return list(
        (await db.execute(select(Scorecard).where(Scorecard.company_id == env.company.id)))
        .scalars()
        .all()
    )


async def _activity(db: AsyncSession, env: Env, type_: str) -> list[ActivityLog]:
    return list(
        (
            await db.execute(
                select(ActivityLog).where(
                    ActivityLog.company_id == env.company.id, ActivityLog.type == type_
                )
            )
        ).scalars()
    )


@pytest.mark.usefixtures("migrated_db")
async def test_booking_requests_scorecard_from_interviewer(
    db_session: AsyncSession,
    mails: dict[str, list[dict[str, Any]]],  # noqa: F811
) -> None:
    env = await _env(db_session)
    interview, slots = await _booked(db_session, env)
    rows = await _rows(db_session, env)
    assert len(rows) == 1
    row = rows[0]
    assert row.reviewer_user_id == env.admin.id
    assert row.interview_id == interview.id
    assert row.due_from == slots[0] + timedelta(minutes=45)
    assert row.requested_by_user_id is None
    assert svc.state_of(row) == "open"
    assert mails["request"] == []
    assert len(await _activity(db_session, env, "scorecard.requested")) == 1


@pytest.mark.usefixtures("migrated_db")
async def test_booking_does_not_duplicate_existing_open_row(db_session: AsyncSession) -> None:
    env = await _env(db_session)
    await svc.request(
        db_session, application=env.app, reviewer=env.admin, requested_by=env.member, notify=False
    )
    await db_session.commit()
    await _booked(db_session, env)
    rows = await _rows(db_session, env)
    assert len(rows) == 1
    assert rows[0].interview_id is None
    assert rows[0].requested_by_user_id == env.member.id


@pytest.mark.usefixtures("migrated_db")
async def test_booking_leaves_submitted_row_alone(db_session: AsyncSession) -> None:
    env = await _env(db_session)
    row = await svc.request(
        db_session, application=env.app, reviewer=env.admin, requested_by=env.member, notify=False
    )
    await svc.submit(db_session, row, ratings={"aaaa1111": 3}, recommendation="yes", comment=None)
    await db_session.commit()
    await _booked(db_session, env)
    rows = await _rows(db_session, env)
    assert len(rows) == 1
    assert svc.state_of(rows[0]) == "submitted"
    assert rows[0].interview_id is None


@pytest.mark.usefixtures("migrated_db")
async def test_booking_reopens_declined_row(db_session: AsyncSession) -> None:
    env = await _env(db_session)
    row = await svc.request(
        db_session, application=env.app, reviewer=env.admin, requested_by=env.member, notify=False
    )
    await svc.decline(db_session, row)
    await db_session.commit()
    interview, _ = await _booked(db_session, env)
    rows = await _rows(db_session, env)
    assert len(rows) == 1
    assert svc.state_of(rows[0]) == "open"
    assert rows[0].interview_id == interview.id


@pytest.mark.usefixtures("migrated_db")
async def test_booking_skips_inactive_interviewer(db_session: AsyncSession) -> None:
    env = await _env(db_session)
    interview = await _interview(db_session, env)
    slots = await _slots(db_session, env)
    env.admin.is_active = False
    await db_session.commit()
    await interviews_service.book(db_session, interview, start=slots[0])
    assert interview.status.value == "booked"
    assert await _rows(db_session, env) == []


@pytest.mark.usefixtures("migrated_db")
async def test_reschedule_moves_due_from_and_resets_reminder(db_session: AsyncSession) -> None:
    env = await _env(db_session)
    interview, slots = await _booked(db_session, env)
    row = (await _rows(db_session, env))[0]
    row.reminded_at = datetime.now(UTC)
    await db_session.commit()
    await interviews_service.reschedule(db_session, interview, start=slots[3])
    row = (await _rows(db_session, env))[0]
    assert row.due_from == slots[3] + timedelta(minutes=45)
    assert row.reminded_at is None


@pytest.mark.usefixtures("migrated_db")
async def test_reschedule_leaves_submitted_row_untouched(db_session: AsyncSession) -> None:
    env = await _env(db_session)
    interview, slots = await _booked(db_session, env)
    row = (await _rows(db_session, env))[0]
    original_due = row.due_from
    await svc.submit(db_session, row, ratings={"aaaa1111": 2}, recommendation="no", comment=None)
    await db_session.commit()
    await interviews_service.reschedule(db_session, interview, start=slots[3])
    row = (await _rows(db_session, env))[0]
    assert row.due_from == original_due
    assert svc.state_of(row) == "submitted"


@pytest.mark.usefixtures("migrated_db")
async def test_reschedule_to_past_end_keeps_reminder_stamp(db_session: AsyncSession) -> None:
    # reschedule() only offers future slots, so exercise the service rule
    # directly: a new end in the past moves due_from but keeps reminded_at
    env = await _env(db_session)
    interview, _ = await _booked(db_session, env)
    row = (await _rows(db_session, env))[0]
    stamp = datetime(2026, 1, 1, tzinfo=UTC)
    row.reminded_at = stamp
    await db_session.commit()
    past_start = datetime(2026, 1, 5, 9, 0, tzinfo=UTC)
    await svc.reschedule_for_interview(
        db_session, interview, start=past_start, now=datetime(2026, 1, 20, tzinfo=UTC)
    )
    await db_session.commit()
    row = (await _rows(db_session, env))[0]
    assert row.due_from == past_start + timedelta(minutes=45)
    assert row.reminded_at == stamp


@pytest.mark.usefixtures("migrated_db")
async def test_staff_cancel_dismisses_auto_request(db_session: AsyncSession) -> None:
    env = await _env(db_session)
    interview, _ = await _booked(db_session, env)
    await interviews_service.cancel_interview(
        db_session, interview, interviewer=env.admin, actor_user_id=env.member.id
    )
    row = (await _rows(db_session, env))[0]
    assert svc.state_of(row) == "dismissed"
    assert row.dismissed_by_user_id == env.member.id
    (entry,) = await _activity(db_session, env, "scorecard.dismissed")
    assert entry.actor_user_id == env.member.id


@pytest.mark.usefixtures("migrated_db")
async def test_candidate_cancel_dismisses_with_no_actor(db_session: AsyncSession) -> None:
    env = await _env(db_session)
    interview, _ = await _booked(db_session, env)
    await interviews_service.candidate_cancel(db_session, interview)
    row = (await _rows(db_session, env))[0]
    assert svc.state_of(row) == "dismissed"
    assert row.dismissed_by_user_id is None
    (entry,) = await _activity(db_session, env, "scorecard.dismissed")
    assert entry.actor_user_id is None
    assert entry.payload["reason"] == "interview_cancelled"
    assert entry.payload["scorecard_id"]


@pytest.mark.usefixtures("migrated_db")
async def test_cancel_leaves_manual_requests_alone(db_session: AsyncSession) -> None:
    env = await _env(db_session)
    await svc.request(
        db_session, application=env.app, reviewer=env.member, requested_by=env.admin, notify=False
    )
    await db_session.commit()
    interview, _ = await _booked(db_session, env)
    await interviews_service.candidate_cancel(db_session, interview)
    states = {r.reviewer_user_id: svc.state_of(r) for r in await _rows(db_session, env)}
    assert states == {env.member.id: "open", env.admin.id: "dismissed"}


@pytest.mark.usefixtures("migrated_db")
async def test_dismiss_for_interview_only_touches_rows_of_that_interview(
    db_session: AsyncSession,
) -> None:
    env = await _env(db_session)
    await svc.request(
        db_session, application=env.app, reviewer=env.member, requested_by=env.admin, notify=False
    )
    await db_session.commit()
    interview, _ = await _booked(db_session, env)
    await svc.dismiss_for_interview(db_session, interview, actor_user_id=env.admin.id)
    await db_session.commit()
    states = {r.reviewer_user_id: svc.state_of(r) for r in await _rows(db_session, env)}
    assert states == {env.member.id: "open", env.admin.id: "dismissed"}
    # a second call finds nothing open and does not raise
    await svc.dismiss_for_interview(db_session, interview, actor_user_id=env.admin.id)


@pytest.mark.usefixtures("migrated_db")
async def test_cancel_commits_dismissal_in_demo_mode(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.core.config import settings

    env = await _env(db_session)
    interview, _ = await _booked(db_session, env)
    monkeypatch.setattr(settings, "demo_mode", True)
    await interviews_service.candidate_cancel(db_session, interview)
    assert [svc.state_of(r) for r in await _rows(db_session, env)] == ["dismissed"]
