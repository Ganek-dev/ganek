"""Demo seed: the ACME Ganek company for local dev, screenshots and the
public demo. Built through the real service layer, idempotent, resettable."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models import (
    ActivityLog,
    Application,
    ApplicationNote,
    ApplicationStage,
    AttemptStatus,
    Candidate,
    Company,
    EmailOutbox,
    EmailStatus,
    Job,
    JobStatus,
    JobView,
    QuizAttempt,
    Scorecard,
    User,
    UserRole,
)
from app.models.application import CLOSED_STAGES
from app.models.scorecard import Recommendation
from app.services import demo_seed, pipeline_signals, quiz, reports, storage
from tests.db import database_reachable, s3_reachable

pytestmark = pytest.mark.skipif(
    not (database_reachable() and s3_reachable()),
    reason="database and object storage required (start postgres+minio or use CI)",
)


async def _count(db: AsyncSession, model: type, company_id: object) -> int:
    return (
        await db.execute(
            select(func.count()).select_from(model).where(model.company_id == company_id)
        )
    ).scalar_one()


@pytest.mark.usefixtures("migrated_db", "seeded_bank", "bucket")
async def test_seed_builds_a_lived_in_workspace_once(db_session: AsyncSession) -> None:
    slug = f"acme-{uuid4().hex[:6]}"
    result = await demo_seed.seed(db_session, slug=slug, password="ganek-demo-1")
    assert result.created is True

    company = (await db_session.execute(select(Company).where(Company.slug == slug))).scalar_one()
    assert company.name == "ACME Ganek"
    assert company.theme["primary_color"] == "#6d28d9"

    users = (
        (await db_session.execute(select(User).where(User.company_id == company.id)))
        .scalars()
        .all()
    )
    assert sorted(u.email for u in users) == [
        f"erika@{slug}.example",
        f"jonas@{slug}.example",
        f"max@{slug}.example",
    ]
    assert {u.role.value for u in users} == {"admin", "member", "reviewer"}
    assert all(u.is_active for u in users)

    jobs = (
        (await db_session.execute(select(Job).where(Job.company_id == company.id))).scalars().all()
    )
    assert len(jobs) == 4 and all(j.status is JobStatus.PUBLISHED for j in jobs)
    assert "Backend Engineer (Python)" in {j.title for j in jobs}

    assert await _count(db_session, Application, company.id) == 17
    assert await _count(db_session, ApplicationNote, company.id) >= 2
    # sent stage mail so the demo timeline shows subjects and text (PR 4)
    mails = (
        (await db_session.execute(select(EmailOutbox).where(EmailOutbox.company_id == company.id)))
        .scalars()
        .all()
    )
    assert {row.kind for row in mails} == {"stage_advance", "rejection"}
    assert all(
        row.status is EmailStatus.SENT and row.rendered_subject and row.rendered_text
        for row in mails
    )
    assert len(mails) == 5  # CANDIDATES: 2 interview + 3 rejected
    assert all(
        "personal-link" in str(row.payload.get("status_url", "personal-link")) for row in mails
    )
    candidates = (
        (await db_session.execute(select(Candidate).where(Candidate.company_id == company.id)))
        .scalars()
        .all()
    )
    assert all(c.email.endswith("@example.com") for c in candidates)

    attempts = (
        (await db_session.execute(select(QuizAttempt).where(QuizAttempt.company_id == company.id)))
        .scalars()
        .all()
    )
    completed = [a for a in attempts if a.status is AttemptStatus.COMPLETED]
    assert len(completed) == 11
    assert all(a.score is not None and 0.0 < a.score < 1.0 for a in completed)
    assert any(a.integrity.get("flags") for a in completed)
    # the blur story names its questions by serve order, the numbering the
    # review page gives the event log, so the two can never disagree
    blurred = next(
        a for a in completed if any(f["code"] == "tab_hidden" for f in a.integrity["flags"])
    )
    flag = next(f for f in blurred.integrity["flags"] if f["code"] == "tab_hidden")
    served = await quiz.resolved_answers(db_session, blurred)
    assert [a.question_id for a in served] == blurred.question_ids  # taken in order
    positions = [i + 1 for i, a in enumerate(served) if a.question_id in flag["question_ids"]]
    assert positions == [3, 5]
    assert flag["detail"].endswith("Occurred during Q3, Q5.")
    # a quiz nobody rushed: answers took seconds, not milliseconds
    assert all(a.integrity.get("avg_answer_ms", 0) > 2000 for a in completed)
    # a lived-in workspace, not one created this second
    assert min(a.created_at for a in attempts) < max(a.created_at for a in attempts)

    stages = {
        row[0].value
        for row in (
            await db_session.execute(
                select(Application.stage).where(Application.company_id == company.id).distinct()
            )
        ).all()
    }
    assert {"new", "screening", "interview", "rejected"} <= stages

    # the stage-age stamp is backdated with the rest: a row that never moved
    # matches created_at, a moved row carries the stamp of the day it moved
    rows = (
        (await db_session.execute(select(Application).where(Application.company_id == company.id)))
        .scalars()
        .all()
    )
    assert all(a.stage_changed_at == a.created_at for a in rows if a.stage is ApplicationStage.NEW)
    assert all(a.stage_changed_at < datetime.now(UTC) - timedelta(hours=1) for a in rows)

    # where the applicants came from: the overview's Sources table has rows
    sources = {
        row[0]
        for row in (
            await db_session.execute(
                select(Application.source).where(Application.company_id == company.id)
            )
        ).all()
    }
    assert {
        "direct",
        "linkedin",
        "google",
        "link:newsletter",
        "ref:robotics-weekly.example",
    } <= sources

    # 30 days of page views for every job, by source, so the tiles, the daily
    # chart and the apply rates read like a live careers page
    view_rows = (
        await db_session.execute(
            select(JobView.job_id, JobView.day, JobView.source, JobView.views)
            .join(Job, Job.id == JobView.job_id)
            .where(Job.company_id == company.id)
        )
    ).all()
    today = datetime.now(UTC).date()
    assert {row.job_id for row in view_rows} == {j.id for j in jobs}
    assert {row.day for row in view_rows} == {today - timedelta(days=i) for i in range(30)}
    assert {"direct", "linkedin", "google", "link:newsletter"} <= {row.source for row in view_rows}
    assert all(row.views > 0 for row in view_rows)
    assert result.views == sum(row.views for row in view_rows) > 1000
    # apply rates stay under 100%: every source with applicants has more views
    backend_job = next(j for j in jobs if j.title == "Backend Engineer (Python)")
    apps_by_source = dict(
        (
            await db_session.execute(
                select(Application.source, func.count())
                .where(Application.job_id == backend_job.id)
                .group_by(Application.source)
            )
        ).all()
    )
    views_by_source: dict[str, int] = {}
    for row in view_rows:
        if row.job_id == backend_job.id:
            views_by_source[row.source] = views_by_source.get(row.source, 0) + row.views
    for source, count in apps_by_source.items():
        assert views_by_source.get(source, 0) > count, source

    # second run: exists, nothing added
    again = await demo_seed.seed(db_session, slug=slug, password="ganek-demo-1")
    assert again.created is False
    assert await _count(db_session, Application, company.id) == 17
    assert await _count(db_session, Scorecard, company.id) == 3
    assert await _count(db_session, User, company.id) == 3


@pytest.fixture
def multi_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "mode", "multi")


@pytest.mark.usefixtures("migrated_db", "seeded_bank", "bucket", "multi_mode")
async def test_seed_includes_scorecards(client: AsyncClient, db_session: AsyncSession) -> None:
    slug = f"acme-{uuid4().hex[:6]}"
    await demo_seed.seed(db_session, slug=slug, password="ganek-demo-1")
    company = (await db_session.execute(select(Company).where(Company.slug == slug))).scalar_one()
    users = {
        u.email: u
        for u in (await db_session.execute(select(User).where(User.company_id == company.id)))
        .scalars()
        .all()
    }
    max_, erika = users[f"max@{slug}.example"], users[f"erika@{slug}.example"]
    assert max_.role is UserRole.REVIEWER and max_.display_name == "Max Berger"

    labels = ["Problem solving", "Communication", "Role knowledge"]
    assert [c["label"] for c in company.scorecard_template] == labels
    jobs = (
        (await db_session.execute(select(Job).where(Job.company_id == company.id))).scalars().all()
    )
    assert all([c["label"] for c in j.scorecard_template] == labels for j in jobs)

    cards = (
        (await db_session.execute(select(Scorecard).where(Scorecard.company_id == company.id)))
        .scalars()
        .all()
    )
    now = datetime.now(UTC)
    submitted = [c for c in cards if c.submitted_at is not None]
    assert len(submitted) == 1
    done = submitted[0]
    assert done.reviewer_user_id == max_.id and done.recommendation is Recommendation.YES
    ids = {c["id"] for c in done.criteria_snapshot}
    assert set(done.ratings) == ids and all(1 <= v <= 4 for v in done.ratings.values())
    assert abs(done.updated_at - done.submitted_at) < timedelta(seconds=1)
    done_app = await db_session.get(Application, done.application_id)
    assert done_app is not None and done_app.stage is ApplicationStage.INTERVIEW

    open_max = next(c for c in cards if c.reviewer_user_id == max_.id and c is not done)
    open_erika = next(c for c in cards if c.reviewer_user_id == erika.id)
    assert open_max.submitted_at is None and open_erika.submitted_at is None
    assert timedelta(days=3, hours=23) < now - open_max.due_from < timedelta(days=4, hours=1)
    assert len({done.application_id, open_max.application_id, open_erika.application_id}) == 3
    assert open_erika.requested_by_user_id not in (None, erika.id)
    assert open_max.requested_by_user_id is not None
    for c in (open_max, open_erika):
        app_row = await db_session.get(Application, c.application_id)
        assert app_row is not None and app_row.stage not in CLOSED_STAGES
        assert [x["label"] for x in c.criteria_snapshot] == labels

    types = [
        (a.type, a.payload.get("reviewer_label"))
        for a in (
            await db_session.execute(
                select(ActivityLog).where(ActivityLog.company_id == company.id)
            )
        )
        .scalars()
        .all()
        if a.type.startswith("scorecard.")
    ]
    assert sorted(types) == [
        ("scorecard.requested", "Erika"),
        ("scorecard.requested", "Max Berger"),
        ("scorecard.requested", "Max Berger"),
        ("scorecard.submitted", "Max Berger"),
    ]

    login = await client.post(
        "/api/v1/auth/login", json={"email": erika.email, "password": "ganek-demo-1"}
    )
    assert login.status_code == 200, login.text
    items = (await client.get("/api/v1/stats/queue")).json()["items"]
    waiting = [i for i in items if i["kind"] == "scorecard-waiting"]
    assert len(waiting) == 1 and waiting[0]["title"].startswith("Waiting on Max Berger")
    assert len([i for i in items if i["kind"] == "scorecard"]) == 1


@pytest.mark.usefixtures("migrated_db", "seeded_bank", "bucket")
async def test_reset_rebuilds_and_removes_the_old_cvs(db_session: AsyncSession) -> None:
    slug = f"acme-{uuid4().hex[:6]}"
    first = await demo_seed.seed(db_session, slug=slug, password="ganek-demo-1")
    old_company_id = first.company_id
    old_keys = [
        row[0]
        for row in (
            await db_session.execute(
                select(Application.cv_object_key).where(Application.company_id == old_company_id)
            )
        ).all()
    ]
    assert len(old_keys) == 17 and await storage.stat_object(old_keys[0]) is not None

    second = await demo_seed.seed(db_session, slug=slug, password="ganek-demo-1", reset=True)
    assert second.created is True and second.company_id != old_company_id
    assert (await db_session.get(Company, old_company_id)) is None
    assert await storage.stat_object(old_keys[0]) is None
    assert await _count(db_session, Application, second.company_id) == 17
    assert await _count(db_session, Scorecard, second.company_id) == 3
    assert await _count(db_session, Scorecard, old_company_id) == 0


async def _seed_company(db: AsyncSession) -> Company:
    slug = f"acme-{uuid4().hex[:6]}"
    await demo_seed.seed(db, slug=slug, password="ganek-demo-1")
    return (await db.execute(select(Company).where(Company.slug == slug))).scalar_one()


@pytest.mark.usefixtures("migrated_db", "seeded_bank", "bucket")
async def test_demo_board_shows_every_chip(db_session: AsyncSession) -> None:
    company = await _seed_company(db_session)
    now = datetime.now(UTC)
    board = await pipeline_signals.board(db_session, company, now=now)
    by_status = {job.status: job for job in board.jobs}
    assert {"stalled", "attention", "on_track"} <= set(by_status)
    assert board.totals.overdue >= 1

    stalled = by_status["stalled"]
    assert sum(stalled.live_by_stage.model_dump().values()) >= 1
    assert stalled.last_movement_at is not None
    assert now - stalled.last_movement_at >= timedelta(days=8)
    assert stalled.new_7d == 0 and stalled.moved_7d == 0

    attention = by_status["attention"]
    assert attention.overdue >= 1
    assert attention.last_movement_at is not None
    assert now - attention.last_movement_at < timedelta(days=3)

    # the nightly reset reruns this at a different "now": history is relative
    assert board.stage_limit_days == pipeline_signals.DEFAULT_STAGE_LIMIT_DAYS


@pytest.mark.usefixtures("migrated_db", "seeded_bank", "bucket")
async def test_demo_jobs_are_open_longer_than_their_oldest_application(
    db_session: AsyncSession,
) -> None:
    company = await _seed_company(db_session)
    now = datetime.now(UTC)
    board = await pipeline_signals.board(db_session, company, now=now)
    assert board.jobs
    for entry in board.jobs:
        oldest = (
            await db_session.execute(
                select(func.min(Application.created_at)).where(Application.job_id == entry.job_id)
            )
        ).scalar_one()
        assert entry.days_open is not None
        if oldest is None:
            continue
        assert entry.days_open >= (now.date() - oldest.date()).days


@pytest.mark.usefixtures("migrated_db", "seeded_bank", "bucket")
async def test_demo_reports_have_history(db_session: AsyncSession) -> None:
    company = await _seed_company(db_session)
    out = await reports.reports(db_session, company, period="90d", job_id=None)
    assert out.cohort.applications >= 10 and out.cohort.hires >= 1
    reached = [step.reached for step in out.funnel]
    assert all(a > b for a, b in zip(reached, reached[1:], strict=False)), reached
    assert reached[-1] >= 1
    # rejections leave from at least two different stages
    assert len({step.stage for step in out.funnel if step.rejected_from > 0}) >= 2
    assert any(t.n >= 3 and t.median_days is not None for t in out.time_in_stage)
    assert len(out.diagnosis) == 2 and not out.diagnosis[0].startswith("Not enough")

    # walking stages queues no mail: only the seeded, already SENT rows exist
    mails = (
        (await db_session.execute(select(EmailOutbox).where(EmailOutbox.company_id == company.id)))
        .scalars()
        .all()
    )
    assert all(row.status is EmailStatus.SENT for row in mails)
