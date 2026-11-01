"""Scorecard sources of the dashboard queue (spec SCORECARDS_SPEC 4.4)."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    Application,
    ApplicationStage,
    Candidate,
    Company,
    Job,
    User,
    UserRole,
)
from app.models.scorecard import Scorecard
from app.services import queue as queue_service
from tests.db import database_reachable

pytestmark = pytest.mark.skipif(
    not database_reachable(), reason="database not reachable (start postgres or use CI)"
)

NOW = datetime(2026, 11, 10, 12, 0, tzinfo=UTC)


class Env:
    def __init__(self, company: Company, app: Application, admin: User, member: User):
        self.company, self.app, self.admin, self.member = company, app, admin, member


def _user(company: Company, role: UserRole, tag: str) -> User:
    return User(
        company_id=company.id,
        email=f"{tag}-{uuid4().hex[:8]}@q.dev",
        password_hash="x",
        role=role,
    )


async def _env(db: AsyncSession) -> Env:
    company = Company(slug=f"q-{uuid4().hex[:8]}", name="Q Co")
    db.add(company)
    await db.flush()
    job = Job(company_id=company.id, slug="dev", title="Dev")
    candidate = Candidate(company_id=company.id, email=f"c-{uuid4().hex[:8]}@x.dev", name="Marta")
    admin = _user(company, UserRole.ADMIN, "admin")
    member = _user(company, UserRole.MEMBER, "member")
    db.add_all([job, candidate, admin, member])
    await db.flush()
    app = Application(
        company_id=company.id,
        job_id=job.id,
        candidate_id=candidate.id,
        cv_object_key=f"cvs/{uuid4().hex}.pdf",
        cv_filename="cv.pdf",
        cv_size=1,
    )
    db.add(app)
    await db.commit()
    return Env(company, app, admin, member)


async def _row(
    db: AsyncSession,
    env: Env,
    *,
    due_days_ago: int,
    requested_by: User | None = None,
    reviewer: User | None = None,
) -> Scorecard:
    due = NOW - timedelta(days=due_days_ago)
    row = Scorecard(
        company_id=env.company.id,
        application_id=env.app.id,
        job_id=env.app.job_id,
        reviewer_user_id=(reviewer or env.member).id,
        requested_by_user_id=requested_by.id if requested_by else None,
        requested_at=due,
        due_from=due,
        criteria_snapshot=[],
        ratings={},
    )
    db.add(row)
    await db.commit()
    return row


async def test_waiting_item_appears_at_three_days_not_two(db_session: AsyncSession) -> None:
    env = await _env(db_session)
    row = await _row(db_session, env, due_days_ago=2, requested_by=env.admin)
    assert await queue_service._scorecards_waiting(db_session, env.company, now=NOW) == []

    row.due_from = NOW - timedelta(days=3)
    await db_session.commit()
    items = await queue_service._scorecards_waiting(db_session, env.company, now=NOW)
    assert len(items) == 1
    item = items[0]
    assert item.key == f"scorecard-waiting:{row.id}"
    assert item.kind == "scorecard-waiting"
    assert item.title == f"Waiting on {env.member.display_label}: Marta"
    assert item.hint == "Dev · 3 days"
    assert item.href == f"/admin/applicants?selected={env.app.id}"
    assert item.since == row.due_from


async def test_own_task_appears_at_day_zero(db_session: AsyncSession) -> None:
    env = await _env(db_session)
    row = await _row(db_session, env, due_days_ago=0, requested_by=env.admin)
    items = await queue_service._scorecards_mine(db_session, env.company, env.member, now=NOW)
    assert len(items) == 1
    item = items[0]
    assert item.key == f"scorecard:{row.id}"
    assert item.kind == "scorecard"
    assert item.title == "Scorecard: Marta"
    assert item.hint == f"Dev · requested by {env.admin.display_label}"
    assert item.href == f"/admin/applicants?selected={env.app.id}&scorecard=1"
    assert item.since == row.requested_at
    # nobody else's queue shows it
    assert await queue_service._scorecards_mine(db_session, env.company, env.admin, now=NOW) == []


async def test_closed_stage_hides_both_items(db_session: AsyncSession) -> None:
    env = await _env(db_session)
    await _row(db_session, env, due_days_ago=5, requested_by=env.admin)
    env.app.stage = ApplicationStage.REJECTED
    await db_session.commit()
    assert await queue_service._scorecards_waiting(db_session, env.company, now=NOW) == []
    mine = await queue_service._scorecards_mine(db_session, env.company, env.member, now=NOW)
    assert mine == []


async def test_dismissed_key_hides_waiting_item(db_session: AsyncSession) -> None:
    env = await _env(db_session)
    row = await _row(db_session, env, due_days_ago=0, requested_by=env.admin)
    # visible_items reads the real clock
    row.due_from = datetime.now(UTC) - timedelta(days=4)
    await db_session.commit()
    key = f"scorecard-waiting:{row.id}"
    items = await queue_service.visible_items(db_session, env.company, env.admin)
    assert key in [i.key for i in items]
    assert await queue_service.dismiss(db_session, env.company, env.admin, key)
    items = await queue_service.visible_items(db_session, env.company, env.admin)
    assert key not in [i.key for i in items]
    # the reviewer's own task is a different key and still shows
    mine = await queue_service.visible_items(db_session, env.company, env.member)
    assert f"scorecard:{row.id}" in [i.key for i in mine]


async def test_submitted_row_yields_no_items(db_session: AsyncSession) -> None:
    env = await _env(db_session)
    row = await _row(db_session, env, due_days_ago=5, requested_by=env.admin)
    row.submitted_at = NOW
    await db_session.commit()
    assert await queue_service._scorecards_waiting(db_session, env.company, now=NOW) == []
    mine = await queue_service._scorecards_mine(db_session, env.company, env.member, now=NOW)
    assert mine == []


async def test_booking_request_hint_reads_from_your_interview(db_session: AsyncSession) -> None:
    env = await _env(db_session)
    await _row(db_session, env, due_days_ago=0, requested_by=None)
    items = await queue_service._scorecards_mine(db_session, env.company, env.member, now=NOW)
    assert items[0].hint == "Dev · from your interview"
