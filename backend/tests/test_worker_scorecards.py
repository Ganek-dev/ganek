"""remind_scorecards cron, called directly with a real DB session factory."""

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import settings
from app.models import (
    Application,
    ApplicationStage,
    Candidate,
    Company,
    Job,
    User,
    UserRole,
)
from app.models.scorecard import Recommendation, Scorecard
from app.services import email as email_service
from app.services import outbox as outbox_service
from app.services import scorecards as svc
from app.worker import remind_scorecards
from tests.db import database_reachable

pytestmark = pytest.mark.skipif(
    not database_reachable(), reason="database not reachable (start postgres or use CI)"
)


class FakeRedis:
    """SET NX that remembers keys, like the claim the cron takes."""

    def __init__(self) -> None:
        self.keys: set[str] = set()

    async def set(self, key: str, value: str, nx: bool = False, ex: int | None = None) -> bool:
        if nx and key in self.keys:
            return False
        self.keys.add(key)
        return True


@pytest.fixture
async def ctx() -> Any:
    engine = create_async_engine(settings.database_url, poolclass=NullPool)
    yield {"session_factory": async_sessionmaker(engine, expire_on_commit=False)}
    await engine.dispose()


@pytest.fixture
def sent(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    monkeypatch.setattr(email_service, "send_scorecard_reminder", lambda **kw: out.append(kw))
    monkeypatch.setattr(email_service, "send_scorecard_request", lambda **kw: None)
    return out


class Env:
    def __init__(self, company: Company, app: Application, admin: User, reviewer: User):
        self.company, self.app, self.admin, self.reviewer = company, app, admin, reviewer


async def _env(db: AsyncSession, *, reviewer_role: UserRole = UserRole.MEMBER) -> Env:
    company = Company(slug=f"rm-{uuid4().hex[:8]}", name="Remind Co")
    db.add(company)
    await db.flush()
    job = Job(company_id=company.id, slug="dev", title="Dev")
    candidate = Candidate(company_id=company.id, email=f"c-{uuid4().hex[:8]}@x.dev", name="Marta")
    admin = User(
        company_id=company.id,
        email=f"a-{uuid4().hex[:8]}@rm.dev",
        password_hash="x",
        role=UserRole.ADMIN,
    )
    reviewer = User(
        company_id=company.id,
        email=f"r-{uuid4().hex[:8]}@rm.dev",
        password_hash="x",
        role=reviewer_role,
    )
    db.add_all([job, candidate, admin, reviewer])
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
    return Env(company, app, admin, reviewer)


async def _request(db: AsyncSession, env: Env, *, days: int) -> Scorecard:
    row = await svc.request(
        db,
        application=env.app,
        reviewer=env.reviewer,
        requested_by=env.admin,
        due_from=datetime.now(UTC) - timedelta(days=days),
        notify=False,
    )
    await db.commit()
    return row


def _ours(sent: list[dict[str, Any]], row: Scorecard) -> list[dict[str, Any]]:
    return [m for m in sent if m["ref"] == str(row.application_id)]


@pytest.mark.usefixtures("migrated_db")
async def test_remind_sends_once_and_marks(
    ctx: Any, db_session: AsyncSession, sent: list[dict[str, Any]]
) -> None:
    env = await _env(db_session)
    row = await _request(db_session, env, days=4)
    await remind_scorecards(ctx)
    mails = _ours(sent, row)
    assert len(mails) == 1
    assert mails[0]["waiting_days"] == 4
    assert mails[0]["to"] == env.reviewer.email
    assert mails[0]["candidate_name"] == "Marta"
    assert mails[0]["url"].endswith(f"?selected={env.app.id}&scorecard=1")
    await db_session.refresh(row)
    assert row.reminded_at is not None
    # no redis in ctx, so no claim: reminded_at alone stops the second run
    await remind_scorecards(ctx)
    assert len(_ours(sent, row)) == 1


@pytest.mark.usefixtures("migrated_db")
async def test_claim_alone_stops_second_run(
    ctx: Any, db_session: AsyncSession, sent: list[dict[str, Any]]
) -> None:
    ctx["redis"] = FakeRedis()
    env = await _env(db_session)
    row = await _request(db_session, env, days=4)
    await remind_scorecards(ctx)
    assert len(_ours(sent, row)) == 1
    # a row that becomes due after the first run is skipped by the claim alone
    env2 = await _env(db_session)
    row2 = await _request(db_session, env2, days=4)
    await remind_scorecards(ctx)
    assert _ours(sent, row2) == []
    await db_session.refresh(row2)
    assert row2.reminded_at is None


@pytest.mark.usefixtures("migrated_db")
async def test_reviewer_role_gets_review_link(
    ctx: Any, db_session: AsyncSession, sent: list[dict[str, Any]]
) -> None:
    env = await _env(db_session, reviewer_role=UserRole.REVIEWER)
    row = await _request(db_session, env, days=3)
    await remind_scorecards(ctx)
    assert _ours(sent, row)[0]["url"].endswith(f"/review/{env.app.id}")


@pytest.mark.usefixtures("migrated_db")
async def test_remind_skips_closed_inactive_and_submitted(
    ctx: Any, db_session: AsyncSession, sent: list[dict[str, Any]]
) -> None:
    closed = await _env(db_session)
    closed_row = await _request(db_session, closed, days=5)
    closed.app.stage = ApplicationStage.REJECTED
    inactive = await _env(db_session)
    inactive_row = await _request(db_session, inactive, days=5)
    inactive.reviewer.is_active = False
    submitted = await _env(db_session)
    submitted_row = await _request(db_session, submitted, days=5)
    await svc.submit(
        db_session,
        submitted_row,
        ratings={},
        recommendation=Recommendation.YES,
        comment=None,
    )
    young = await _env(db_session)
    young_row = await _request(db_session, young, days=2)
    await db_session.commit()
    await remind_scorecards(ctx)
    for r in (closed_row, inactive_row, submitted_row, young_row):
        assert _ours(sent, r) == []
        await db_session.refresh(r)
        assert r.reminded_at is None or r is submitted_row


@pytest.mark.usefixtures("migrated_db")
async def test_rerequest_after_decline_is_reminded_again(
    ctx: Any, db_session: AsyncSession, sent: list[dict[str, Any]]
) -> None:
    env = await _env(db_session)
    row = await _request(db_session, env, days=4)
    await remind_scorecards(ctx)
    assert len(_ours(sent, row)) == 1
    await db_session.refresh(row)  # the cron committed reminded_at from its own session
    await svc.decline(db_session, row)
    await db_session.commit()
    await svc.request(
        db_session,
        application=env.app,
        reviewer=env.reviewer,
        requested_by=env.admin,
        due_from=datetime.now(UTC) - timedelta(days=3),
        notify=False,
    )
    await db_session.commit()
    await remind_scorecards(ctx)  # no redis in ctx: the claim is out of the way
    assert len(_ours(sent, row)) == 2


@pytest.mark.usefixtures("migrated_db")
async def test_demo_mode_sends_nothing_but_marks(
    ctx: Any,
    db_session: AsyncSession,
    sent: list[dict[str, Any]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "demo_mode", True)
    env = await _env(db_session)
    row = await _request(db_session, env, days=4)
    await remind_scorecards(ctx)
    assert _ours(sent, row) == []
    await db_session.refresh(row)
    assert row.reminded_at is not None


@pytest.mark.usefixtures("migrated_db")
async def test_one_failing_row_does_not_stop_the_rest(
    ctx: Any,
    db_session: AsyncSession,
    sent: list[dict[str, Any]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bad = await _env(db_session)
    bad_row = await _request(db_session, bad, days=6)  # oldest first, so it runs first
    good = await _env(db_session)
    good_row = await _request(db_session, good, days=4)
    real = outbox_service.queue_email

    async def flaky(db: AsyncSession, **kw: Any) -> Any:
        if kw["company_id"] == bad.company.id:
            raise RuntimeError("boom")
        return await real(db, **kw)

    monkeypatch.setattr(outbox_service, "queue_email", flaky)
    await remind_scorecards(ctx)
    assert _ours(sent, bad_row) == []
    assert len(_ours(sent, good_row)) == 1
    await db_session.refresh(bad_row)
    await db_session.refresh(good_row)
    assert bad_row.reminded_at is None  # rolled back, retried tomorrow
    assert good_row.reminded_at is not None
