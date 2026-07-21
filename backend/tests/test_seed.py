from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Difficulty, Question, QuestionStatus
from app.services.seed import questions_dir, seed_questions
from tests.db import database_reachable

pytestmark = pytest.mark.skipif(
    not database_reachable(), reason="database not reachable (start postgres or use CI)"
)


def _bank() -> Path:
    directory = questions_dir()
    assert directory is not None, "question bank must be auto-detected in the repo checkout"
    return directory


@pytest.mark.usefixtures("migrated_db")
async def test_seed_inserts_and_is_idempotent(db_session: AsyncSession) -> None:
    directory = _bank()
    first = await seed_questions(db_session, directory)
    assert first.created + first.unchanged + first.updated >= 6  # bundled bank

    second = await seed_questions(db_session, directory)
    assert second.created == 0
    assert second.updated == 0
    assert second.unchanged >= 6


@pytest.mark.usefixtures("migrated_db")
async def test_seeded_question_shape(db_session: AsyncSession) -> None:
    await seed_questions(db_session, _bank())
    question = (
        await db_session.execute(select(Question).where(Question.id == "py-asyncio-gather-1"))
    ).scalar_one()
    assert question.domain == "software-engineering"
    assert set(question.tags) >= {"asyncio", "python"}  # file tag + extra tags merged
    assert question.difficulty is Difficulty.MEDIUM
    assert question.status is QuestionStatus.ACTIVE
    assert question.company_id is None
    assert set(question.options) == {"a", "b", "c", "d"}
    assert question.correct_key == "a"
    assert question.time_limit_seconds == 15


@pytest.mark.usefixtures("migrated_db")
async def test_seed_applies_edits_on_reseed(db_session: AsyncSession) -> None:
    directory = _bank()
    await seed_questions(db_session, directory)

    # simulate a stale DB row that the YAML has since corrected
    question = (
        await db_session.execute(select(Question).where(Question.id == "py-gil-1"))
    ).scalar_one()
    question.prompt_md = "OUTDATED PROMPT"
    await db_session.commit()

    report = await seed_questions(db_session, directory)
    assert report.updated >= 1
    await db_session.refresh(question)
    assert question.prompt_md != "OUTDATED PROMPT"
