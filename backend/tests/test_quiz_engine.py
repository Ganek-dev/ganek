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
    Questionnaire,
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


@pytest.mark.usefixtures("migrated_db")
async def test_company_questions_join_the_pool_and_stay_private(
    db_session: AsyncSession,
) -> None:
    from app.models import Question, QuestionSource

    company, job, application = await _fixture(db_session)
    unique_tag = f"secret-{uuid4().hex[:8]}"
    db_session.add(
        Question(
            id=f"co-{uuid4().hex[:16]}",
            company_id=company.id,
            domain="company",
            tags=[unique_tag],
            difficulty=2,
            prompt_md="Company-internal question?",
            options={"a": "Yes", "b": "No", "c": "Maybe", "d": "42"},
            correct_key="a",
            source=QuestionSource.COMPANY,
        )
    )
    job.quiz_config = {"enabled": True, "tags": [unique_tag], "question_count": 1}
    await db_session.commit()

    attempt = await quiz.create_attempt(db_session, company, application, job)
    assert attempt is not None
    assert len(attempt.question_ids) == 1
    assert attempt.question_ids[0].startswith("co-")

    # another company with the same tag config gets nothing (private pool)
    other = Company(slug=f"other-{uuid4().hex[:8]}", name="Other Co")
    db_session.add(other)
    await db_session.flush()
    other_job = Job(
        company_id=other.id,
        slug="py-dev",
        title="Py Dev",
        quiz_config={"enabled": True, "tags": [unique_tag], "question_count": 1},
    )
    other_candidate = Candidate(
        company_id=other.id, email=f"c-{uuid4().hex[:8]}@vetd-ci.dev", name="X"
    )
    db_session.add_all([other_job, other_candidate])
    await db_session.flush()
    other_application = Application(
        company_id=other.id,
        job_id=other_job.id,
        candidate_id=other_candidate.id,
        cv_object_key=f"cvs/{other.id}/{uuid4().hex}.pdf",
        cv_filename="cv.pdf",
        cv_size=1000,
    )
    db_session.add(other_application)
    await db_session.commit()
    assert await quiz.create_attempt(db_session, other, other_application, other_job) is None


# Curated questionnaire attach path (D4). The engine must swap tag-auto
# selection for the questionnaire's ordered refs while still honouring
# time limits, exclusions and tenant scoping.


async def _attach_questionnaire(
    db_session: AsyncSession,
    company: Company,
    job: Job,
    *,
    refs: list[str],
    shuffle: bool = False,
    excludes: list[str] | None = None,
) -> Questionnaire:
    questionnaire = Questionnaire(
        company_id=company.id,
        name=f"Q-{uuid4().hex[:6]}",
        shuffle=shuffle,
        question_refs=refs,
    )
    db_session.add(questionnaire)
    await db_session.flush()
    job.quiz_config = {
        **job.quiz_config,
        "enabled": True,
        "questionnaire_id": str(questionnaire.id),
        "exclude_ids": excludes or [],
    }
    await db_session.commit()
    return questionnaire


@pytest.mark.usefixtures("migrated_db")
async def test_attached_questionnaire_freezes_curated_order(
    db_session: AsyncSession,
) -> None:
    company, job, application = await _fixture(db_session)
    refs = ["py-mutable-default-1", "py-gil-1", "py-dict-ordering-1"]
    await _attach_questionnaire(db_session, company, job, refs=refs)
    attempt = await quiz.create_attempt(
        db_session, company, application, job, rng=random.Random(11)
    )
    assert attempt is not None
    # order preserved, count = refs length (question_count ignored)
    assert attempt.question_ids == refs


@pytest.mark.usefixtures("migrated_db")
async def test_attached_questionnaire_shuffle_reorders_but_keeps_set(
    db_session: AsyncSession,
) -> None:
    company, job, application = await _fixture(db_session)
    refs = ["py-mutable-default-1", "py-gil-1", "py-dict-ordering-1", "py-fstring-eval-1"]
    await _attach_questionnaire(db_session, company, job, refs=refs, shuffle=True)
    attempt = await quiz.create_attempt(db_session, company, application, job, rng=random.Random(7))
    assert attempt is not None
    assert sorted(attempt.question_ids) == sorted(refs)
    assert attempt.question_ids != refs  # rng=7 does reshuffle these four


@pytest.mark.usefixtures("migrated_db")
async def test_attached_questionnaire_honors_excludes(
    db_session: AsyncSession,
) -> None:
    company, job, application = await _fixture(db_session)
    refs = ["py-mutable-default-1", "py-gil-1", "py-dict-ordering-1"]
    await _attach_questionnaire(db_session, company, job, refs=refs, excludes=["py-gil-1"])
    attempt = await quiz.create_attempt(db_session, company, application, job, rng=random.Random(1))
    assert attempt is not None
    assert attempt.question_ids == ["py-mutable-default-1", "py-dict-ordering-1"]


@pytest.mark.usefixtures("migrated_db")
async def test_missing_questionnaire_yields_no_attempt(
    db_session: AsyncSession,
) -> None:
    company, job, application = await _fixture(db_session)
    job.quiz_config = {
        **job.quiz_config,
        "enabled": True,
        "questionnaire_id": str(uuid4()),
    }
    await db_session.commit()
    assert await quiz.create_attempt(db_session, company, application, job) is None


@pytest.mark.usefixtures("migrated_db")
async def test_preview_reflects_attached_questionnaire(
    db_session: AsyncSession,
) -> None:
    company, job, application = await _fixture(db_session)
    refs = ["py-mutable-default-1", "py-gil-1", "py-dict-ordering-1"]
    await _attach_questionnaire(db_session, company, job, refs=refs, excludes=["py-gil-1"])
    config, pool, eligible, sample = await quiz.build_quiz_preview(
        db_session, company, job, rng=random.Random(1)
    )
    assert config.questionnaire_id is not None
    assert {q.id for q in pool} == set(refs)
    assert eligible == {"py-mutable-default-1", "py-dict-ordering-1"}
    assert sample == ["py-mutable-default-1", "py-dict-ordering-1"]
