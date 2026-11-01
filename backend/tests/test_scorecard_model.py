from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Application, Candidate, Company, Job, User, UserRole
from app.models.scorecard import Recommendation, Scorecard
from tests.db import database_reachable

pytestmark = pytest.mark.skipif(
    not database_reachable(), reason="database not reachable (start postgres or use CI)"
)

_CRITERIA = [
    {"id": "ab12cd34", "label": "Problem solving"},
    {"id": "ef56ab78", "label": "Communication"},
]


async def _fixture(db: AsyncSession) -> tuple[Company, Job, Application, User]:
    company = Company(slug=f"scco-{uuid4().hex[:8]}", name="Sc Co")
    db.add(company)
    await db.flush()
    job = Job(company_id=company.id, slug="backend-dev", title="Backend Dev")
    candidate = Candidate(
        company_id=company.id, email=f"cand-{uuid4().hex[:8]}@ganek-ci.dev", name="Marta"
    )
    reviewer = User(
        company_id=company.id,
        email=f"rev-{uuid4().hex[:8]}@scco.dev",
        password_hash="x",
        role=UserRole.MEMBER,
    )
    db.add_all([job, candidate, reviewer])
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
    return company, job, application, reviewer


def _scorecard(company: Company, job: Job, application: Application, reviewer: User) -> Scorecard:
    return Scorecard(
        company_id=company.id,
        application_id=application.id,
        job_id=job.id,
        reviewer_user_id=reviewer.id,
        requested_by_user_id=reviewer.id,
        due_from=application.created_at,
        criteria_snapshot=_CRITERIA,
    )


@pytest.mark.usefixtures("migrated_db")
async def test_scorecard_round_trip(db_session: AsyncSession) -> None:
    company, job, application, reviewer = await _fixture(db_session)
    card = _scorecard(company, job, application, reviewer)
    card.ratings = {"ab12cd34": 3}
    db_session.add(card)
    await db_session.commit()
    await db_session.refresh(card)
    assert card.criteria_snapshot == _CRITERIA
    assert card.ratings == {"ab12cd34": 3}
    assert card.recommendation is None
    assert card.requested_at is not None
    assert card.submitted_at is None
    assert card.reviewer.id == reviewer.id


@pytest.mark.usefixtures("migrated_db")
async def test_recommendation_stores_lowercase_value(db_session: AsyncSession) -> None:
    company, job, application, reviewer = await _fixture(db_session)
    card = _scorecard(company, job, application, reviewer)
    card.recommendation = Recommendation.STRONG_YES
    db_session.add(card)
    await db_session.commit()
    raw = (
        await db_session.execute(
            text("SELECT recommendation FROM scorecards WHERE id = :i"), {"i": card.id}
        )
    ).scalar_one()
    assert raw == "strong_yes"


@pytest.mark.usefixtures("migrated_db")
async def test_duplicate_open_request_rejected(db_session: AsyncSession) -> None:
    company, job, application, reviewer = await _fixture(db_session)
    db_session.add(_scorecard(company, job, application, reviewer))
    await db_session.commit()
    db_session.add(_scorecard(company, job, application, reviewer))
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()


@pytest.mark.usefixtures("migrated_db")
async def test_users_role_check_accepts_reviewer(db_session: AsyncSession) -> None:
    _, _, _, user = await _fixture(db_session)
    await db_session.execute(
        text("UPDATE users SET role = 'reviewer' WHERE id = :i"), {"i": user.id}
    )
    with pytest.raises(IntegrityError):
        await db_session.execute(
            text("UPDATE users SET role = 'owner' WHERE id = :i"), {"i": user.id}
        )
    await db_session.rollback()


@pytest.mark.usefixtures("migrated_db")
async def test_template_columns_default_empty_list(db_session: AsyncSession) -> None:
    company, job, _, _ = await _fixture(db_session)
    await db_session.refresh(company)
    await db_session.refresh(job)
    assert company.scorecard_template == []
    assert job.scorecard_template == []


def test_display_label_former_teammate() -> None:
    live = User(email="jane.doe@acme.example", display_name="Jane D.")
    assert live.is_anonymized is False
    assert live.display_label == "Jane D."
    gone = User(email=f"deleted-{uuid4().hex}@invalid", display_name=None)
    assert gone.is_anonymized is True
    assert gone.display_label == "Former teammate"
