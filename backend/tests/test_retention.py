"""Nightly retention purge (G3, Art. 5(1)(e)): terminal applications past the
company window are erased via the G2 primitives, orphaned candidates and
expired invites are swept, and abandoned CV uploads are garbage-collected.

`now` is injected everywhere so window math and the 24 h upload grace are
deterministic — no sleeping, no clock games.
"""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tests.db import database_reachable, s3_reachable

pytestmark = pytest.mark.skipif(
    not (database_reachable() and s3_reachable()),
    reason="database and object storage required (start postgres+minio or use CI)",
)

NOW = datetime.now(UTC)


async def _company(db: AsyncSession, *, retention_months: int | None = None) -> object:
    from app.models import Company

    settings_json = {} if retention_months is None else {"retention_months": retention_months}
    company = Company(slug=f"rt-{uuid4().hex[:8]}", name="Retention Co", settings=settings_json)
    db.add(company)
    await db.flush()
    return company


async def _application(
    db: AsyncSession,
    company: object,
    *,
    stage: str,
    decided_days_ago: int | None,
    with_cv_object: bool = False,
) -> tuple[object, object, str]:
    """Fabricated job+candidate+application. Returns (application_id, candidate_id, cv_key)."""
    from app.models import Application, ApplicationStage, Candidate, Job
    from app.services import storage

    job = Job(company_id=company.id, slug=f"job-{uuid4().hex[:8]}", title="Role")
    candidate = Candidate(
        company_id=company.id, email=f"c-{uuid4().hex[:8]}@ganek-ci.dev", name="Ret Candidate"
    )
    db.add_all([job, candidate])
    await db.flush()
    cv_key = storage.build_cv_key(company.id)
    if with_cv_object:
        await storage.put_object(cv_key, b"%PDF-1.4 retention", storage.CV_CONTENT_TYPE)
    application = Application(
        company_id=company.id,
        job_id=job.id,
        candidate_id=candidate.id,
        cv_object_key=cv_key,
        cv_filename="cv.pdf",
        cv_size=123,
        stage=ApplicationStage(stage),
        decided_at=None if decided_days_ago is None else NOW - timedelta(days=decided_days_ago),
    )
    db.add(application)
    await db.flush()
    # plain values, NOT ORM objects: expire_all() in _exists would make any
    # later attribute access a sync lazy-refresh -> MissingGreenlet on async
    return application.id, candidate.id, cv_key


async def _exists(db: AsyncSession, model: type, row_id: object) -> bool:
    db.expire_all()
    return (
        await db.execute(select(model.id).where(model.id == row_id))
    ).scalar_one_or_none() is not None


@pytest.mark.usefixtures("migrated_db", "bucket")
async def test_purge_removes_expired_terminal_applications(db_session: AsyncSession) -> None:
    from app.models import ActivityLog, Application, Candidate
    from app.services import retention, storage

    company = await _company(db_session, retention_months=6)
    company_id = company.id  # before any _exists() expire_all
    expired_app, expired_cand, expired_key = await _application(
        db_session, company, stage="rejected", decided_days_ago=200, with_cv_object=True
    )
    fresh_app, fresh_cand, _ = await _application(
        db_session, company, stage="rejected", decided_days_ago=10
    )
    await db_session.commit()

    summary = await retention.run_purge(db_session, now=NOW)
    # sums are instance-global (leftover tenants in a dev DB may add to them);
    # the company-scoped receipt below carries the exact assertion
    assert summary.applications >= 1
    assert summary.candidates >= 1

    assert not await _exists(db_session, Application, expired_app)
    assert not await _exists(db_session, Candidate, expired_cand)
    assert await _exists(db_session, Application, fresh_app)
    assert await _exists(db_session, Candidate, fresh_cand)
    assert await storage.stat_object(expired_key) is None

    receipts = list(
        (
            await db_session.execute(
                select(ActivityLog).where(
                    ActivityLog.company_id == company_id,
                    ActivityLog.type == "retention.purged",
                )
            )
        ).scalars()
    )
    assert len(receipts) == 1
    assert receipts[0].payload == {"applications": 1, "candidates": 1}
    assert receipts[0].application_id is None


@pytest.mark.usefixtures("migrated_db", "bucket")
async def test_purge_respects_stage_rules(db_session: AsyncSession) -> None:
    from app.models import Application
    from app.services import retention

    company = await _company(db_session)
    hired_app, _, _ = await _application(db_session, company, stage="hired", decided_days_ago=400)
    withdrawn_app, _, _ = await _application(
        db_session, company, stage="withdrawn", decided_days_ago=200
    )
    live_app, _, _ = await _application(db_session, company, stage="new", decided_days_ago=None)
    await db_session.commit()

    await retention.run_purge(db_session, now=NOW)

    assert await _exists(db_session, Application, hired_app)  # employee context
    assert not await _exists(db_session, Application, withdrawn_app)
    assert await _exists(db_session, Application, live_app)


@pytest.mark.usefixtures("migrated_db", "bucket")
async def test_purge_keeps_candidates_with_live_applications(db_session: AsyncSession) -> None:
    from app.models import Application, ApplicationStage, Candidate, Job
    from app.services import retention

    company = await _company(db_session)
    expired_app, candidate_id, _ = await _application(
        db_session, company, stage="rejected", decided_days_ago=200
    )
    # second, live application for the SAME candidate
    job2 = Job(company_id=company.id, slug=f"job-{uuid4().hex[:8]}", title="Role 2")
    db_session.add(job2)
    await db_session.flush()
    live_row = Application(
        company_id=company.id,
        job_id=job2.id,
        candidate_id=candidate_id,
        cv_object_key=f"cvs/{company.id}/{uuid4().hex}.pdf",
        cv_filename="cv.pdf",
        cv_size=123,
        stage=ApplicationStage.SCREENING,
    )
    db_session.add(live_row)
    await db_session.flush()
    live_app = live_row.id
    await db_session.commit()

    await retention.run_purge(db_session, now=NOW)

    assert not await _exists(db_session, Application, expired_app)
    assert await _exists(db_session, Application, live_app)
    assert await _exists(db_session, Candidate, candidate_id)


@pytest.mark.usefixtures("migrated_db", "bucket")
async def test_purge_honors_custom_window_and_default(db_session: AsyncSession) -> None:
    from app.models import Application
    from app.services import retention

    short_co = await _company(db_session, retention_months=1)
    short_app, _, _ = await _application(
        db_session, short_co, stage="rejected", decided_days_ago=45
    )
    default_co = await _company(db_session)  # no key -> default 6
    default_app, _, _ = await _application(
        db_session, default_co, stage="rejected", decided_days_ago=45
    )
    await db_session.commit()

    await retention.run_purge(db_session, now=NOW)

    assert not await _exists(db_session, Application, short_app)  # 45d > 1*31d
    assert await _exists(db_session, Application, default_app)  # 45d < 6*31d


@pytest.mark.usefixtures("migrated_db", "bucket")
async def test_purge_skips_on_storage_failure_and_continues(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.models import Application
    from app.services import erasure, retention, storage

    company = await _company(db_session)
    blocked_app, _, blocked_key = await _application(
        db_session, company, stage="rejected", decided_days_ago=200
    )
    ok_app, _, _ = await _application(db_session, company, stage="rejected", decided_days_ago=200)
    await db_session.commit()

    real_delete = storage.delete_object

    async def flaky_delete(object_key: str) -> None:
        if object_key == blocked_key:
            raise RuntimeError("storage down for this key")
        await real_delete(object_key)

    monkeypatch.setattr(erasure.storage, "delete_object", flaky_delete)

    summary = await retention.run_purge(db_session, now=NOW)
    assert summary.applications == 1  # the healthy one

    assert await _exists(db_session, Application, blocked_app)  # retried next night
    assert not await _exists(db_session, Application, ok_app)


@pytest.mark.usefixtures("migrated_db", "bucket")
async def test_sweeps_invites_and_orphan_cvs(db_session: AsyncSession) -> None:
    from app.models import UserInvite, UserRole
    from app.services import retention, storage

    company = await _company(db_session)
    # a referenced application object must never be swept, however old
    _, _, referenced_key = await _application(
        db_session, company, stage="new", decided_days_ago=None, with_cv_object=True
    )
    expired_invite = UserInvite(
        company_id=company.id,
        email="old@ganek-ci.dev",
        role=UserRole.MEMBER,
        expires_at=NOW - timedelta(days=1),
    )
    live_invite = UserInvite(
        company_id=company.id,
        email="new@ganek-ci.dev",
        role=UserRole.MEMBER,
        expires_at=NOW + timedelta(days=5),
    )
    db_session.add_all([expired_invite, live_invite])
    await db_session.flush()
    expired_invite_id, live_invite_id = expired_invite.id, live_invite.id
    await db_session.commit()

    orphan_key = storage.build_cv_key(company.id)
    await storage.put_object(orphan_key, b"%PDF-1.4 abandoned", storage.CV_CONTENT_TYPE)

    # within the 24h grace the orphan survives (upload-then-apply race)
    await retention.run_purge(db_session, now=NOW)
    assert await storage.stat_object(orphan_key) is not None

    # past the grace it goes; the referenced object stays
    summary = await retention.run_purge(db_session, now=NOW + timedelta(hours=25))
    assert summary.cv_objects >= 1
    assert await storage.stat_object(orphan_key) is None
    assert await storage.stat_object(referenced_key) is not None

    assert not await _exists(db_session, UserInvite, expired_invite_id)
    assert await _exists(db_session, UserInvite, live_invite_id)


def _request_task(company_id: object, name: str, email: str, **overrides: object) -> object:
    """A task shaped exactly like the public request endpoints create them
    (the shape itself is pinned by the endpoint-driven test in test_erasure)."""
    from app.models import Task

    fields: dict[str, object] = {
        "company_id": company_id,
        "created_by": None,
        "title": f"Privacy: deletion request — {name}",
        "note": f"{name} ({email}) asked via their status page (Role). "
        "GDPR clock: respond within one month.",
    }
    fields.update(overrides)
    return Task(**fields)


@pytest.mark.usefixtures("migrated_db", "bucket")
async def test_purge_scrubs_tasks_of_purged_candidates(db_session: AsyncSession) -> None:
    """A candidate the retention purge erases must not live on inside the
    privacy-request task that once named them."""
    from app.models import Candidate, Task
    from app.services import retention

    company = await _company(db_session, retention_months=6)
    company_id = company.id
    _, purged_cand, _ = await _application(
        db_session, company, stage="rejected", decided_days_ago=200
    )
    _, live_cand, _ = await _application(db_session, company, stage="new", decided_days_ago=None)
    emails = {
        cand_id: (
            await db_session.execute(select(Candidate.email).where(Candidate.id == cand_id))
        ).scalar_one()
        for cand_id in (purged_cand, live_cand)
    }
    purged_task = _request_task(company_id, "Ret Candidate", emails[purged_cand])
    live_task = _request_task(company_id, "Ret Candidate", emails[live_cand])
    db_session.add_all([purged_task, live_task])
    await db_session.flush()
    purged_task_id, live_task_id = purged_task.id, live_task.id
    await db_session.commit()

    await retention.run_purge(db_session, now=NOW)

    assert not await _exists(db_session, Candidate, purged_cand)
    assert not await _exists(db_session, Task, purged_task_id)
    assert await _exists(db_session, Task, live_task_id)


@pytest.mark.usefixtures("migrated_db", "bucket")
async def test_purge_sweeps_done_privacy_tasks(db_session: AsyncSession) -> None:
    """Completed request tasks are swept 90 days after done_at: still-open
    requests and humans' own tasks are never touched, however old."""
    from app.models import Task, User, UserRole
    from app.services import retention

    company = await _company(db_session)
    company_id = company.id
    human = User(
        company_id=company_id,
        email=f"rec-{uuid4().hex[:8]}@ganek-ci.dev",
        password_hash="x",
        role=UserRole.MEMBER,
    )
    db_session.add(human)
    await db_session.flush()
    old_done = _request_task(
        company_id, "Old Done", "old@ganek-ci.dev", done_at=NOW - timedelta(days=91)
    )
    fresh_done = _request_task(
        company_id, "Fresh Done", "fresh@ganek-ci.dev", done_at=NOW - timedelta(days=10)
    )
    still_open = _request_task(company_id, "Still Open", "open@ganek-ci.dev")
    human_done = _request_task(
        company_id,
        "Human Done",
        "human@ganek-ci.dev",
        created_by=human.id,
        done_at=NOW - timedelta(days=400),
    )
    db_session.add_all([old_done, fresh_done, still_open, human_done])
    await db_session.flush()
    ids = {
        "old_done": old_done.id,
        "fresh_done": fresh_done.id,
        "still_open": still_open.id,
        "human_done": human_done.id,
    }
    await db_session.commit()

    summary = await retention.run_purge(db_session, now=NOW)
    assert summary.privacy_tasks >= 1  # instance-global, like the other sums

    assert not await _exists(db_session, Task, ids["old_done"])
    assert await _exists(db_session, Task, ids["fresh_done"])
    assert await _exists(db_session, Task, ids["still_open"])
    assert await _exists(db_session, Task, ids["human_done"])


@pytest.mark.usefixtures("migrated_db", "bucket")
async def test_worker_job_runs_and_cron_registered(db_session: AsyncSession) -> None:
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from sqlalchemy.pool import NullPool

    from app import worker
    from app.core.config import settings as app_settings

    engine = create_async_engine(app_settings.database_url, poolclass=NullPool)
    ctx = {"session_factory": async_sessionmaker(engine, expire_on_commit=False)}
    try:
        await worker.purge_retention(ctx)  # smoke: no raise on a quiet database
    finally:
        await engine.dispose()

    assert any(
        getattr(job, "coroutine", None) is worker.purge_retention
        or getattr(getattr(job, "coroutine", None), "__name__", "") == "purge_retention"
        for job in worker.WorkerSettings.cron_jobs
    )
