from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Application, ApplicationStage, Candidate, Company, Job
from tests.db import database_reachable

pytestmark = pytest.mark.skipif(
    not database_reachable(), reason="database not reachable (start postgres or use CI)"
)


async def _fixture(db: AsyncSession) -> tuple[Company, Job, Candidate]:
    company = Company(slug=f"appco-{uuid4().hex[:8]}", name="App Co")
    db.add(company)
    await db.flush()
    job = Job(company_id=company.id, slug="backend-dev", title="Backend Dev")
    candidate = Candidate(
        company_id=company.id, email=f"cand-{uuid4().hex[:8]}@ganek-ci.dev", name="Jane Doe"
    )
    db.add_all([job, candidate])
    await db.commit()
    return company, job, candidate


def _application(company: Company, job: Job, candidate: Candidate) -> Application:
    return Application(
        company_id=company.id,
        job_id=job.id,
        candidate_id=candidate.id,
        cv_object_key=f"cvs/{uuid4().hex}.pdf",
        cv_filename="jane-doe-cv.pdf",
        cv_size=123_456,
    )


@pytest.mark.usefixtures("migrated_db")
async def test_application_roundtrip_defaults(db_session: AsyncSession) -> None:
    company, job, candidate = await _fixture(db_session)
    db_session.add(_application(company, job, candidate))
    await db_session.commit()

    loaded = (
        await db_session.execute(select(Application).where(Application.job_id == job.id))
    ).scalar_one()
    assert loaded.stage is ApplicationStage.NEW
    assert loaded.message is None
    assert loaded.source is None
    assert loaded.cv_filename == "jane-doe-cv.pdf"


@pytest.mark.usefixtures("migrated_db")
async def test_one_application_per_candidate_per_job(db_session: AsyncSession) -> None:
    company, job, candidate = await _fixture(db_session)
    db_session.add(_application(company, job, candidate))
    await db_session.commit()
    db_session.add(_application(company, job, candidate))
    with pytest.raises(IntegrityError):
        await db_session.commit()


@pytest.mark.usefixtures("migrated_db")
async def test_candidate_email_unique_per_company(db_session: AsyncSession) -> None:
    company, _, candidate = await _fixture(db_session)
    db_session.add(Candidate(company_id=company.id, email=candidate.email, name="Clone"))
    with pytest.raises(IntegrityError):
        await db_session.commit()
