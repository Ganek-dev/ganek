from uuid import uuid4

import httpx
import pytest
from httpx import AsyncClient

from app.core.config import settings
from app.schemas.public import PracticeQuestionOut, QuizQuestionOut
from tests.db import database_reachable, s3_reachable

pytestmark = pytest.mark.skipif(
    not (database_reachable() and s3_reachable()),
    reason="database and object storage required (start postgres+minio or use CI)",
)

PDF_BYTES = b"%PDF-1.4 quiz flow"
QUIZ_CONFIG = {"enabled": True, "tags": ["python", "asyncio"], "question_count": 4}


@pytest.fixture
def multi_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "mode", "multi")


async def _apply_with_quiz(client: AsyncClient, *, quiz_config: dict | None = None) -> str | None:
    """Register company + quiz-enabled job, apply as candidate; returns quiz_token."""
    name = f"Quiz Co {uuid4().hex[:6]}"
    resp = await client.post(
        "/api/v1/auth/register",
        json={
            "company_name": name,
            "email": f"admin-{uuid4().hex[:8]}@ganek-ci.dev",
            "password": "a-long-secure-password",
        },
    )
    assert resp.status_code == 201, resp.text
    slug = name.lower().replace(" ", "-")

    job = (
        await client.post(
            "/api/v1/jobs", json={"title": "Python Dev", "tags": ["python", "asyncio"]}
        )
    ).json()
    if quiz_config is not None:
        # quiz_config is not exposed via the API yet — set it directly
        from sqlalchemy import update
        from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
        from sqlalchemy.pool import NullPool

        from app.core.config import settings as app_settings
        from app.models import Job

        engine = create_async_engine(app_settings.database_url, poolclass=NullPool)
        async with async_sessionmaker(engine)() as db:
            await db.execute(update(Job).where(Job.id == job["id"]).values(quiz_config=quiz_config))
            await db.commit()
        await engine.dispose()
    assert (await client.post(f"/api/v1/jobs/{job['id']}/publish")).status_code == 200
    await client.post("/api/v1/auth/logout")

    base = f"/api/v1/public/companies/{slug}/jobs/{job['slug']}"
    ticket = (await client.post(f"{base}/apply/upload-url")).json()
    async with httpx.AsyncClient() as raw:
        assert (
            await raw.put(
                ticket["upload_url"],
                content=PDF_BYTES,
                headers={"Content-Type": ticket["content_type"]},
            )
        ).status_code == 200
    resp = await client.post(
        f"{base}/apply",
        json={
            "name": "Jane",
            "email": f"jane-{uuid4().hex[:8]}@ganek-ci.dev",
            "cv_object_key": ticket["object_key"],
            "cv_filename": "cv.pdf",
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["quiz_token"]


def test_candidate_schema_has_no_answer_fields() -> None:
    # the serializer-level guard from ANTI_CHEAT.md / CLAUDE hard rule #1
    forbidden = {"correct_key", "correct", "explanation_md", "explanation"}
    assert not forbidden & set(QuizQuestionOut.model_fields)
    assert not forbidden & set(PracticeQuestionOut.model_fields)


@pytest.mark.usefixtures("migrated_db", "seeded_bank", "bucket", "multi_mode")
async def test_apply_issues_quiz_token_and_full_run(client: AsyncClient) -> None:
    token = await _apply_with_quiz(client, quiz_config=QUIZ_CONFIG)
    assert token is not None

    state = (await client.get(f"/api/v1/public/quiz/{token}")).json()
    assert state["status"] == "pending"
    assert state["answered"] == 0
    assert state["total"] == 4
    # intro context for the start gate (screen 18)
    assert state["candidate_name"] == "Jane"
    assert state["company_name"].startswith("Quiz Co")
    assert state["job_title"] == "Python Dev"
    assert state["expires_at"] is not None
    assert state["practice_available"] is True
    # the start-gate acknowledgment links the full telemetry disclosure
    assert state["privacy_url"].endswith("/privacy")
    assert "correct" not in str(state)
    # the finished screen links the status page via the same payload
    status = await client.get(f"/api/v1/public/applications/{state['status_token']}")
    assert status.status_code == 200
    assert status.json()["job_title"] == "Python Dev"

    seen: set[str] = set()
    for expected_index in range(1, 5):
        resp = await client.post(f"/api/v1/public/quiz/{token}/next")
        assert resp.status_code == 200, resp.text
        # the answer must never ride along in any candidate-facing payload
        assert "correct_key" not in resp.text
        assert "explanation" not in resp.text
        body = resp.json()
        assert body["done"] is False
        question = body["question"]
        assert question["index"] == expected_index
        assert question["total"] == 4
        assert len(question["options"]) == 4
        seen.add(question["id"])

        resp = await client.post(
            f"/api/v1/public/quiz/{token}/answer",
            json={"question_id": question["id"], "answer_key": question["options"][0]["key"]},
        )
        assert resp.status_code == 200
        assert resp.json() == {"recorded": True}  # no correctness feedback

    assert len(seen) == 4
    done = (await client.post(f"/api/v1/public/quiz/{token}/next")).json()
    assert done == {"done": True, "question": None}
    state = (await client.get(f"/api/v1/public/quiz/{token}")).json()
    assert state["status"] == "completed"
    assert state["answered"] == 4


@pytest.mark.usefixtures("migrated_db", "seeded_bank", "bucket", "multi_mode")
async def test_quiz_disabled_job_issues_no_token(client: AsyncClient) -> None:
    token = await _apply_with_quiz(client, quiz_config=None)
    assert token is None


@pytest.mark.usefixtures("migrated_db", "seeded_bank", "bucket", "multi_mode")
async def test_bogus_and_unserved_answers_rejected(client: AsyncClient) -> None:
    token = await _apply_with_quiz(client, quiz_config=QUIZ_CONFIG)
    assert token is not None

    assert (await client.get("/api/v1/public/quiz/not-a-token")).status_code == 404
    # answering before anything was served → 409
    resp = await client.post(
        f"/api/v1/public/quiz/{token}/answer",
        json={"question_id": "py-gil-1", "answer_key": "a"},
    )
    assert resp.status_code == 409
    # malformed answer key rejected by validation
    served = (await client.post(f"/api/v1/public/quiz/{token}/next")).json()["question"]
    resp = await client.post(
        f"/api/v1/public/quiz/{token}/answer",
        json={"question_id": served["id"], "answer_key": "z"},
    )
    assert resp.status_code == 422


@pytest.mark.usefixtures("migrated_db", "seeded_bank", "bucket", "multi_mode")
async def test_integrity_events_aggregate_and_flag(client: AsyncClient) -> None:
    token = await _apply_with_quiz(client, quiz_config=QUIZ_CONFIG)
    assert token is not None

    # complete the quiz quickly, reporting events tied to the first question
    first_question_id: str | None = None
    while True:
        body = (await client.post(f"/api/v1/public/quiz/{token}/next")).json()
        if body["done"]:
            break
        question = body["question"]
        if first_question_id is None:
            first_question_id = question["id"]
            resp = await client.post(
                f"/api/v1/public/quiz/{token}/events",
                json={
                    "events": [
                        {"type": "blur", "duration_ms": 12000, "question_id": question["id"]},
                        {"type": "blur", "duration_ms": 8000, "question_id": question["id"]},
                        {"type": "paste", "question_id": question["id"]},
                        {"type": "resize"},
                    ]
                },
            )
            assert resp.status_code == 200
        await client.post(
            f"/api/v1/public/quiz/{token}/answer",
            json={"question_id": question["id"], "answer_key": question["options"][0]["key"]},
        )

    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from sqlalchemy.pool import NullPool

    from app.core.security import read_quiz_token
    from app.services.quiz import get_attempt_by_id

    engine = create_async_engine(settings.database_url, poolclass=NullPool)
    async with async_sessionmaker(engine, expire_on_commit=False)() as db:
        attempt_id = read_quiz_token(token)
        assert attempt_id is not None
        attempt = await get_attempt_by_id(db, attempt_id)
        assert attempt is not None
        integrity = attempt.integrity
    await engine.dispose()

    assert integrity["blur_count"] == 2
    assert integrity["blur_total_ms"] == 20000
    assert integrity["paste_count"] == 1
    assert integrity["resize_count"] == 1
    assert integrity["avg_answer_ms"] < 3000
    assert len(integrity["events"]) == 4

    flags = {flag["code"]: flag for flag in integrity["flags"]}
    assert flags["tab_hidden"]["summary"] == "left the tab 2x (~20s)"
    assert "Q1" in flags["tab_hidden"]["detail"]  # reasoning names the question
    assert flags["tab_hidden"]["question_ids"] == [first_question_id]
    assert flags["paste"]["question_ids"] == [first_question_id]
    assert "external tooling" in flags["paste"]["detail"]
    assert flags["very_fast"]["question_ids"]  # all four were fast
    assert "guessing" in flags["very_fast"]["detail"]


@pytest.mark.usefixtures("migrated_db", "seeded_bank", "bucket", "multi_mode")
async def test_integrity_events_validation(client: AsyncClient) -> None:
    token = await _apply_with_quiz(client, quiz_config=QUIZ_CONFIG)
    assert token is not None
    resp = await client.post(
        f"/api/v1/public/quiz/{token}/events",
        json={"events": [{"type": "webcam_off"}]},
    )
    assert resp.status_code == 422


@pytest.mark.usefixtures("migrated_db", "seeded_bank", "bucket", "multi_mode")
async def test_practice_serves_sample_questions_without_recording(client: AsyncClient) -> None:
    token = await _apply_with_quiz(client, quiz_config=QUIZ_CONFIG)
    assert token is not None
    real_ids = set()

    # practice while pending: sample question, never from the real quiz
    for _ in range(3):
        resp = await client.post(f"/api/v1/public/quiz/{token}/practice")
        assert resp.status_code == 200, resp.text
        assert "correct_key" not in resp.text
        assert "explanation" not in resp.text
        question = resp.json()["question"]
        assert question is not None
        assert len(question["options"]) == 4
        assert question["time_limit_seconds"] > 0

    # the attempt is untouched: still pending, nothing answered
    state = (await client.get(f"/api/v1/public/quiz/{token}")).json()
    assert state["status"] == "pending"
    assert state["answered"] == 0

    # the real run never serves a practice-served question? No — practice
    # questions are excluded FROM the real set, so collect the real ids
    # and assert practice never overlapped them.
    practice_ids = set()
    resp = await client.post(f"/api/v1/public/quiz/{token}/practice")
    practice_ids.add(resp.json()["question"]["id"])
    while True:
        body = (await client.post(f"/api/v1/public/quiz/{token}/next")).json()
        if body["done"]:
            break
        real_ids.add(body["question"]["id"])
        await client.post(
            f"/api/v1/public/quiz/{token}/answer",
            json={
                "question_id": body["question"]["id"],
                "answer_key": body["question"]["options"][0]["key"],
            },
        )
    assert practice_ids.isdisjoint(real_ids)


@pytest.mark.usefixtures("migrated_db", "seeded_bank", "bucket", "multi_mode")
async def test_practice_is_gated_to_pending_attempts(client: AsyncClient) -> None:
    token = await _apply_with_quiz(client, quiz_config=QUIZ_CONFIG)
    assert token is not None
    # starting the real assessment closes the practice window
    assert (await client.post(f"/api/v1/public/quiz/{token}/next")).status_code == 200
    resp = await client.post(f"/api/v1/public/quiz/{token}/practice")
    assert resp.status_code == 409
