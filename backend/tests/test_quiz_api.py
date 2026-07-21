from uuid import uuid4

import httpx
import pytest
from httpx import AsyncClient

from app.core.config import settings
from app.schemas.public import QuizQuestionOut
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
            "email": f"admin-{uuid4().hex[:8]}@vetd-ci.dev",
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
            "email": f"jane-{uuid4().hex[:8]}@vetd-ci.dev",
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


@pytest.mark.usefixtures("migrated_db", "seeded_bank", "bucket", "multi_mode")
async def test_apply_issues_quiz_token_and_full_run(client: AsyncClient) -> None:
    token = await _apply_with_quiz(client, quiz_config=QUIZ_CONFIG)
    assert token is not None

    state = (await client.get(f"/api/v1/public/quiz/{token}")).json()
    assert state == {"status": "pending", "answered": 0, "total": 4}

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
