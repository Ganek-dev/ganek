from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Company, EmploymentType, Job, JobStatus, RemotePolicy
from tests.db import database_reachable

pytestmark = pytest.mark.skipif(
    not database_reachable(), reason="database not reachable (start postgres or use CI)"
)


async def _make_company(db: AsyncSession) -> Company:
    company = Company(slug=f"jobco-{uuid4().hex[:8]}", name="Job Co")
    db.add(company)
    await db.commit()
    return company


@pytest.mark.usefixtures("migrated_db")
async def test_job_roundtrip_with_defaults(db_session: AsyncSession) -> None:
    company = await _make_company(db_session)
    job = Job(
        company_id=company.id,
        slug="senior-python-developer",
        title="Senior Python Developer",
        tags=["python", "fastapi", "backend"],
    )
    db_session.add(job)
    await db_session.commit()

    loaded = (
        await db_session.execute(select(Job).where(Job.company_id == company.id))
    ).scalar_one()
    assert loaded.status is JobStatus.DRAFT
    assert loaded.remote_policy is RemotePolicy.ONSITE
    assert loaded.employment_type is EmploymentType.FULL_TIME
    assert loaded.description_md == ""
    assert loaded.published_at is None
    assert loaded.quiz_config == {}
    assert loaded.salary_min is None
    assert loaded.tags == ["python", "fastapi", "backend"]


@pytest.mark.usefixtures("migrated_db")
async def test_job_slug_unique_per_company(db_session: AsyncSession) -> None:
    company = await _make_company(db_session)
    db_session.add(Job(company_id=company.id, slug="backend-dev", title="Backend Dev"))
    await db_session.commit()
    db_session.add(Job(company_id=company.id, slug="backend-dev", title="Backend Dev 2"))
    with pytest.raises(IntegrityError):
        await db_session.commit()


@pytest.mark.usefixtures("migrated_db")
async def test_same_slug_allowed_across_companies(db_session: AsyncSession) -> None:
    first = await _make_company(db_session)
    second = await _make_company(db_session)
    db_session.add(Job(company_id=first.id, slug="backend-dev", title="Backend Dev"))
    db_session.add(Job(company_id=second.id, slug="backend-dev", title="Backend Dev"))
    await db_session.commit()


@pytest.mark.usefixtures("migrated_db")
async def test_jobs_filterable_by_tag(db_session: AsyncSession) -> None:
    company = await _make_company(db_session)
    db_session.add(
        Job(company_id=company.id, slug="py-dev", title="Python Dev", tags=["python", "backend"])
    )
    db_session.add(
        Job(company_id=company.id, slug="ts-dev", title="TS Dev", tags=["typescript", "frontend"])
    )
    await db_session.commit()

    result = (
        (
            await db_session.execute(
                select(Job).where(Job.company_id == company.id, Job.tags.contains(["python"]))
            )
        )
        .scalars()
        .all()
    )
    assert [j.slug for j in result] == ["py-dev"]
