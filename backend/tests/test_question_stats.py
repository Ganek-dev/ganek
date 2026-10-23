"""Difficulty calibration from real answer stats: a per-question report over
this workspace's completed quizzes. Informs a questions: PR; nothing in
scoring or selection reads it."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models import Application, AttemptAnswer, AttemptStatus, QuizAttempt
from app.services import questions as questions_service
from tests.db import database_reachable, s3_reachable
from tests.test_dashboard_api import _company_with_applicant

db_required = pytest.mark.skipif(
    not (database_reachable() and s3_reachable()),
    reason="database and object storage required (start postgres+minio or use CI)",
)


@pytest.fixture
def multi_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "mode", "multi")


# --- DB-free: the hint rule ----------------------------------------------------


def test_hint_needs_a_sample_floor() -> None:
    assert questions_service.calibration_hint(3, served=19, correct=19) is None
    assert questions_service.calibration_hint(3, served=20, correct=20) == "easier"


def test_hint_fires_only_outside_the_band_by_a_margin() -> None:
    # difficulty 3 expects 50-70% correct; the margin is 10 points either side
    assert questions_service.calibration_hint(3, served=100, correct=60) is None
    assert questions_service.calibration_hint(3, served=100, correct=80) is None
    assert questions_service.calibration_hint(3, served=100, correct=81) == "easier"
    assert questions_service.calibration_hint(3, served=100, correct=40) is None
    assert questions_service.calibration_hint(3, served=100, correct=39) == "harder"


def test_hint_has_no_easier_than_one_and_no_harder_than_five() -> None:
    assert questions_service.calibration_hint(1, served=100, correct=100) is None
    assert questions_service.calibration_hint(1, served=100, correct=50) == "harder"
    assert questions_service.calibration_hint(5, served=100, correct=0) is None
    assert questions_service.calibration_hint(5, served=100, correct=60) == "easier"


# --- API ---------------------------------------------------------------------


async def _attempt_with_answers(
    db: AsyncSession,
    application: Application,
    *,
    status: AttemptStatus,
    answers: list[tuple[str, bool | None, int]],
) -> None:
    """answers: (question_id, is_correct or None for a timeout, response seconds)."""
    now = datetime.now(UTC)
    attempt = QuizAttempt(
        company_id=application.company_id,
        application_id=application.id,
        status=status,
        question_ids=[qid for qid, _, _ in answers],
        started_at=now - timedelta(minutes=5),
        completed_at=now if status is AttemptStatus.COMPLETED else None,
        expires_at=now + timedelta(days=1),
        score=0.5,
        integrity={},
    )
    db.add(attempt)
    await db.flush()
    for qid, correct, seconds in answers:
        served = now - timedelta(minutes=4)
        db.add(
            AttemptAnswer(
                attempt_id=attempt.id,
                question_id=qid,
                option_order=["a", "b", "c", "d"],
                served_at=served,
                deadline_at=served + timedelta(seconds=22),
                answered_at=served + timedelta(seconds=seconds),
                answer_key=None if correct is None else ("a" if correct else "b"),
                is_correct=bool(correct),
            )
        )
    await db.commit()


@db_required
@pytest.mark.usefixtures("migrated_db", "seeded_bank", "bucket", "multi_mode")
async def test_stats_count_only_this_workspaces_completed_attempts(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    application_id, _, _ = await _company_with_applicant(client)
    bank = (await client.get("/api/v1/questions/bank?limit=3")).json()["items"]
    q1, q2, q3 = (item["id"] for item in bank)
    application = (
        await db_session.execute(select(Application).where(Application.id == application_id))
    ).scalar_one()
    # counted: a completed attempt, two answers on q1 (one right, one timed out), one on q2
    await _attempt_with_answers(
        db_session,
        application,
        status=AttemptStatus.COMPLETED,
        answers=[(q1, True, 8), (q1, None, 22), (q2, False, 12)],
    )
    # counted: a second completed run on q1 (re-issue history still has evidence)
    await _attempt_with_answers(
        db_session, application, status=AttemptStatus.COMPLETED, answers=[(q1, True, 4)]
    )
    # not counted: an invalidated attempt carries no evidence
    await _attempt_with_answers(
        db_session, application, status=AttemptStatus.INVALIDATED, answers=[(q1, True, 3)]
    )

    resp = await client.get(f"/api/v1/questions/stats?ids={q1},{q2},{q3}")
    assert resp.status_code == 200, resp.text
    stats = resp.json()
    assert set(stats) == {q1, q2}  # q3 was never served here
    assert stats[q1]["served"] == 3
    assert stats[q1]["correct_rate"] == pytest.approx(2 / 3)
    assert stats[q1]["timeout_rate"] == pytest.approx(1 / 3)
    assert stats[q1]["avg_response_ms"] == 6000  # answered ones only: 8s and 4s
    assert stats[q1]["hint"] is None  # far below the 20-answer floor
    assert stats[q2] == {
        "served": 1,
        "correct_rate": 0.0,
        "timeout_rate": 0.0,
        "avg_response_ms": 12000,
        "hint": None,
    }

    # another workspace sees none of it
    await client.post("/api/v1/auth/logout")
    await _company_with_applicant(client)
    assert (await client.get(f"/api/v1/questions/stats?ids={q1},{q2}")).json() == {}


@db_required
@pytest.mark.usefixtures("migrated_db", "seeded_bank", "bucket", "multi_mode")
async def test_stats_hint_fires_with_enough_answers(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    application_id, _, _ = await _company_with_applicant(client)
    hard = (await client.get("/api/v1/questions/bank?difficulty=4&limit=1")).json()["items"][0]
    application = (
        await db_session.execute(select(Application).where(Application.id == application_id))
    ).scalar_one()
    # 20 completed runs, 19 right: a rated-4 question nobody misses
    for i in range(20):
        await _attempt_with_answers(
            db_session,
            application,
            status=AttemptStatus.COMPLETED,
            answers=[(hard["id"], i != 0, 6)],
        )
    stats = (await client.get(f"/api/v1/questions/stats?ids={hard['id']}")).json()
    assert stats[hard["id"]]["served"] == 20
    assert stats[hard["id"]]["hint"] == "easier"


@db_required
@pytest.mark.usefixtures("migrated_db", "seeded_bank", "bucket", "multi_mode")
async def test_stats_need_a_session(client: AsyncClient) -> None:
    assert (
        await client.get(f"/api/v1/questions/stats?ids=py-{uuid4().hex[:6]}")
    ).status_code == 401
