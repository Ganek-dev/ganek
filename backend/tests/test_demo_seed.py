"""Demo seed: the ACME Ganek company for local dev, screenshots and the
public demo. Built through the real service layer, idempotent, resettable."""

from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    Application,
    ApplicationNote,
    AttemptStatus,
    Candidate,
    Company,
    Job,
    JobStatus,
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
