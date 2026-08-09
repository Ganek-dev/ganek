from uuid import uuid4

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    Application,
    Candidate,
    Company,
    Interview,
    InterviewStatus,
    Job,
    User,
    UserRole,
)
from tests.db import database_reachable

pytestmark = pytest.mark.skipif(
    not database_reachable(), reason="database not reachable (start postgres or use CI)"
)


async def _fixture(db: AsyncSession) -> tuple[Company, Application, User]:
    company = Company(slug=f"ivco-{uuid4().hex[:8]}", name="Iv Co")
    db.add(company)
    await db.flush()
    job = Job(company_id=company.id, slug="backend-dev", title="Backend Dev")
    candidate = Candidate(
        company_id=company.id, email=f"cand-{uuid4().hex[:8]}@vetd-ci.dev", name="Marta"
    )
    interviewer = User(
        company_id=company.id,
        email=f"dana-{uuid4().hex[:8]}@ivco.dev",
        password_hash="x",
        role=UserRole.MEMBER,
    )
    db.add_all([job, candidate, interviewer])
    await db.flush()
    application = Application(
        company_id=company.id,
        job_id=job.id,
        candidate_id=candidate.id,
        cv_object_key=f"cvs/{uuid4().hex}.pdf",
        cv_filename="cv.pdf",
        cv_size=1000,
    )
    db.add(application)
    await db.commit()
    return company, application, interviewer


def _interview(company: Company, application: Application, interviewer: User) -> Interview:
    return Interview(
        company_id=company.id,
        application_id=application.id,
        interviewer_user_id=interviewer.id,
        duration_minutes=45,
        timezone="Europe/Berlin",
    )


@pytest.mark.usefixtures("migrated_db")
async def test_interview_roundtrip_defaults(db_session: AsyncSession) -> None:
    company, application, interviewer = await _fixture(db_session)
    interview = _interview(company, application, interviewer)
    db_session.add(interview)
    await db_session.commit()
    assert interview.status is InterviewStatus.PENDING
    assert interview.title == "Hiring manager interview"
    assert interview.scheduled_start is None
    assert interview.meet_url is None


@pytest.mark.usefixtures("migrated_db")
async def test_one_active_interview_per_application(db_session: AsyncSession) -> None:
    company, application, interviewer = await _fixture(db_session)
    db_session.add(_interview(company, application, interviewer))
    await db_session.commit()
    db_session.add(_interview(company, application, interviewer))
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()


@pytest.mark.usefixtures("migrated_db")
async def test_cancelled_interview_allows_a_new_request(db_session: AsyncSession) -> None:
    company, application, interviewer = await _fixture(db_session)
    first = _interview(company, application, interviewer)
    first.status = InterviewStatus.CANCELLED
    db_session.add(first)
    await db_session.commit()
    db_session.add(_interview(company, application, interviewer))
    await db_session.commit()  # partial index permits this
