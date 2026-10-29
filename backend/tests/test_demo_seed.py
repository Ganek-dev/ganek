"""Demo seed: the ACME Ganek company for local dev, screenshots and the
public demo. Built through the real service layer, idempotent, resettable."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    Application,
    ApplicationNote,
    ApplicationStage,
    AttemptStatus,
    Candidate,
    Company,
    Job,
    JobStatus,
    JobView,
    QuizAttempt,
    User,
)
from app.services import demo_seed, storage
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
    ]
    assert {u.role.value for u in users} == {"admin", "member"}
    assert all(u.is_active for u in users)

    jobs = (
        (await db_session.execute(select(Job).where(Job.company_id == company.id))).scalars().all()
    )
    assert len(jobs) == 4 and all(j.status is JobStatus.PUBLISHED for j in jobs)
    assert "Backend Engineer (Python)" in {j.title for j in jobs}

    assert await _count(db_session, Application, company.id) == 17
    assert await _count(db_session, ApplicationNote, company.id) >= 2
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
