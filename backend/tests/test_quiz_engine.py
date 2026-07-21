import random
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    Application,
    AttemptStatus,
    Candidate,
    Company,
    Job,
    Question,
)
from app.services import quiz
from app.services.seed import questions_dir, seed_questions
from tests.db import database_reachable

pytestmark = pytest.mark.skipif(
    not database_reachable(), reason="database not reachable (start postgres or use CI)"
)

QUIZ_CONFIG = {"enabled": True, "tags": ["python", "asyncio"], "question_count": 4}


async def _fixture(db: AsyncSession) -> tuple[Company, Job, Application]:
    directory = questions_dir()
    assert directory is not None
    await seed_questions(db, directory)

    company = Company(slug=f"quizco-{uuid4().hex[:8]}", name="Quiz Co")
    db.add(company)
    await db.flush()
    job = Job(
        company_id=company.id,
        slug="py-dev",
        title="Python Dev",
        tags=["python"],
        quiz_config=QUIZ_CONFIG,
    )
    candidate = Candidate(
        company_id=company.id, email=f"c-{uuid4().hex[:8]}@vetd-ci.dev", name="Jane"
    )
    db.add_all([job, candidate])
    await db.flush()
    application = Application(
        company_id=company.id,
        job_id=job.id,
        candidate_id=candidate.id,
        cv_object_key=f"cvs/{company.id}/{uuid4().hex}.pdf",
        cv_filename="cv.pdf",
        cv_size=1000,
    )
    db.add(application)
    await db.commit()
    return company, job, application


@pytest.mark.usefixtures("migrated_db")
async def test_attempt_selection_is_stratified_and_frozen(db_session: AsyncSession) -> None:
    company, job, application = await _fixture(db_session)
    attempt = await quiz.create_attempt(
        db_session, company, application, job, rng=random.Random(42)
    )
    assert attempt is not None
    assert len(attempt.question_ids) == 4
    assert len(set(attempt.question_ids)) == 4

    questions = {
        q.id: q
        for q in (
            await db_session.execute(select(Question).where(Question.id.in_(attempt.question_ids)))
        ).scalars()
    }
    # both requested tags represented (bank has ≥3 of each)
    assert any("python" in q.tags for q in questions.values())
    assert any("asyncio" in q.tags for q in questions.values())


@pytest.mark.usefixtures("migrated_db")
async def test_quiz_disabled_means_no_attempt(db_session: AsyncSession) -> None:
    company, job, application = await _fixture(db_session)
    job.quiz_config = {"enabled": False}
    await db_session.commit()
    assert await quiz.create_attempt(db_session, company, application, job) is None


@pytest.mark.usefixtures("migrated_db")
async def test_full_run_scores_and_breaks_down_by_tag(db_session: AsyncSession) -> None:
    company, job, application = await _fixture(db_session)
    attempt = await quiz.create_attempt(db_session, company, application, job, rng=random.Random(1))
    assert attempt is not None

    answered_wrong_once = False
    while True:
        served = await quiz.current_or_next_question(db_session, attempt)
        if served is None:
            break
        answer, question = served
        assert set(answer.option_order) == set(question.options.keys())  # shuffled permutation
        key = question.correct_key
        if not answered_wrong_once:
            key = next(k for k in question.options if k != question.correct_key)
            answered_wrong_once = True
        await quiz.submit_answer(db_session, attempt, question.id, key)

    assert attempt.status is AttemptStatus.COMPLETED
    assert attempt.score == pytest.approx(3 / 4)
    assert attempt.completed_at is not None
    totals = {tag: bucket["total"] for tag, bucket in attempt.per_tag_scores.items()}
    assert sum(totals.values()) >= 4  # questions carry multiple tags


@pytest.mark.usefixtures("migrated_db")
async def test_reconnect_serves_same_question_same_deadline(db_session: AsyncSession) -> None:
    company, job, application = await _fixture(db_session)
    attempt = await quiz.create_attempt(db_session, company, application, job, rng=random.Random(2))
    assert attempt is not None
    first = await quiz.current_or_next_question(db_session, attempt)
    second = await quiz.current_or_next_question(db_session, attempt)
    assert first is not None and second is not None
    assert first[0].id == second[0].id
    assert first[0].deadline_at == second[0].deadline_at


@pytest.mark.usefixtures("migrated_db")
async def test_late_answer_scores_zero(db_session: AsyncSession) -> None:
    company, job, application = await _fixture(db_session)
    attempt = await quiz.create_attempt(db_session, company, application, job, rng=random.Random(3))
    assert attempt is not None
    served = await quiz.current_or_next_question(db_session, attempt)
    assert served is not None
    answer, question = served
    answer.deadline_at = datetime.now(UTC) - timedelta(seconds=1)
    await db_session.commit()

    result = await quiz.submit_answer(db_session, attempt, question.id, question.correct_key)
    assert result.answer_key == question.correct_key  # recorded for review
    assert result.is_correct is False  # but scored zero


@pytest.mark.usefixtures("migrated_db")
async def test_missed_question_resolved_on_next_serve(db_session: AsyncSession) -> None:
    company, job, application = await _fixture(db_session)
    attempt = await quiz.create_attempt(db_session, company, application, job, rng=random.Random(4))
    assert attempt is not None
    served = await quiz.current_or_next_question(db_session, attempt)
    assert served is not None
    answer, question = served
    answer.deadline_at = datetime.now(UTC) - timedelta(seconds=1)
    await db_session.commit()

    next_served = await quiz.current_or_next_question(db_session, attempt)
    assert next_served is not None
    assert next_served[1].id != question.id
    await db_session.refresh(answer)
    assert answer.answered_at is not None
    assert answer.answer_key is None
    assert answer.is_correct is False
    # a resolved question can no longer be answered
    with pytest.raises(quiz.NoOpenQuestionError):
        await quiz.submit_answer(db_session, attempt, question.id, "a")


@pytest.mark.usefixtures("migrated_db")
async def test_unstarted_attempt_expires(db_session: AsyncSession) -> None:
    company, job, application = await _fixture(db_session)
    attempt = await quiz.create_attempt(db_session, company, application, job, rng=random.Random(5))
    assert attempt is not None
    attempt.expires_at = datetime.now(UTC) - timedelta(hours=1)
    await db_session.commit()
    with pytest.raises(quiz.AttemptExpiredError):
        await quiz.current_or_next_question(db_session, attempt)
    assert attempt.status is AttemptStatus.EXPIRED
