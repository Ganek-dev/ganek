"""Candidate status page (screen 21): magic-link status + withdraw."""

from uuid import uuid4

import httpx
import pytest
from httpx import AsyncClient

from app.core.config import settings
from tests.db import database_reachable, s3_reachable

pytestmark = pytest.mark.skipif(
    not (database_reachable() and s3_reachable()),
    reason="database and object storage required (start postgres+minio or use CI)",
)

PDF_BYTES = b"%PDF-1.4 status flow"


@pytest.fixture
def multi_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "mode", "multi")


async def _apply(
    client: AsyncClient, *, with_quiz: bool = False
) -> tuple[dict[str, str | None], dict[str, str]]:
    """Register + publish + apply; returns (apply response json, admin creds)."""
    creds = {
        "email": f"admin-{uuid4().hex[:8]}@vetd-ci.dev",
        "password": "a-long-secure-password",
    }
    name = f"Status Co {uuid4().hex[:6]}"
    resp = await client.post("/api/v1/auth/register", json={"company_name": name, **creds})
    assert resp.status_code == 201, resp.text
    slug = name.lower().replace(" ", "-")
    job_payload: dict[str, object] = {"title": "Backend Engineer"}
    if with_quiz:
        job_payload["tags"] = ["python"]
        job_payload["quiz_config"] = {"enabled": True, "question_count": 2}
    job = (await client.post("/api/v1/jobs", json=job_payload)).json()
    assert (await client.post(f"/api/v1/jobs/{job['id']}/publish")).status_code == 200
    await client.post("/api/v1/auth/logout")

    base = f"/api/v1/public/companies/{slug}/jobs/{job['slug']}"
    ticket = (await client.post(f"{base}/apply/upload-url")).json()
    async with httpx.AsyncClient() as raw:
        put = await raw.put(
            ticket["upload_url"],
            content=PDF_BYTES,
            headers={"Content-Type": ticket["content_type"]},
        )
        assert put.status_code == 200
    resp = await client.post(
        f"{base}/apply",
        json={
            "name": "Marta Vidal",
            "email": f"marta-{uuid4().hex[:8]}@vetd-ci.dev",
            "cv_object_key": ticket["object_key"],
            "cv_filename": "marta-vidal-cv.pdf",
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json(), creds


@pytest.mark.usefixtures("migrated_db", "bucket", "multi_mode")
async def test_apply_returns_status_token_and_status_renders(client: AsyncClient) -> None:
    received, _ = await _apply(client)
    token = received["status_token"]
    assert token

    resp = await client.get(f"/api/v1/public/applications/{token}")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["candidate_name"] == "Marta Vidal"
    assert body["company_name"].startswith("Status Co")
    assert body["job_title"] == "Backend Engineer"
    assert body["cv_filename"] == "marta-vidal-cv.pdf"
    assert body["stage"] == "new"
    assert body["quiz"] is None  # job had no assessment
    assert body["applied_at"] is not None
    assert body["decision_expected_by"] > body["applied_at"]


@pytest.mark.usefixtures("migrated_db", "seeded_bank", "bucket", "multi_mode")
async def test_status_shows_quiz_progress(client: AsyncClient) -> None:
    received, _ = await _apply(client, with_quiz=True)
    status_token = received["status_token"]
    quiz_token = received["quiz_token"]
    assert quiz_token

    body = (await client.get(f"/api/v1/public/applications/{status_token}")).json()
    assert body["quiz"] == {
        "status": "pending",
        "answered": 0,
        "total": 2,
        "completed_at": None,
    }

    while True:
        step = (await client.post(f"/api/v1/public/quiz/{quiz_token}/next")).json()
        if step["done"]:
            break
        await client.post(
            f"/api/v1/public/quiz/{quiz_token}/answer",
            json={
                "question_id": step["question"]["id"],
                "answer_key": step["question"]["options"][0]["key"],
            },
        )

    body = (await client.get(f"/api/v1/public/applications/{status_token}")).json()
    assert body["quiz"]["status"] == "completed"
    assert body["quiz"]["answered"] == 2
    assert body["quiz"]["completed_at"] is not None
    # candidate-facing: the score must never appear
    assert "score" not in str(body)


@pytest.mark.usefixtures("migrated_db", "bucket", "multi_mode")
async def test_withdraw_is_idempotent_and_final_stages_conflict(client: AsyncClient) -> None:
    received, creds = await _apply(client)
    token = received["status_token"]

    resp = await client.post(f"/api/v1/public/applications/{token}/withdraw")
    assert resp.status_code == 200
    body = (await client.get(f"/api/v1/public/applications/{token}")).json()
    assert body["stage"] == "withdrawn"

    # withdrawing again stays 200 (idempotent)
    assert (await client.post(f"/api/v1/public/applications/{token}/withdraw")).status_code == 200

    # a decided application cannot be withdrawn
    assert (await client.post("/api/v1/auth/login", json=creds)).status_code == 200
    app = (await client.get("/api/v1/applications")).json()["items"][0]
    resp = await client.patch(f"/api/v1/applications/{app['id']}/stage", json={"stage": "rejected"})
    assert resp.status_code == 200
    await client.post("/api/v1/auth/logout")
    assert (await client.post(f"/api/v1/public/applications/{token}/withdraw")).status_code == 409


@pytest.mark.usefixtures("migrated_db", "bucket", "multi_mode")
async def test_status_rejects_bad_tokens(client: AsyncClient) -> None:
    assert (await client.get("/api/v1/public/applications/not-a-token")).status_code == 404
    assert (
        await client.post("/api/v1/public/applications/not-a-token/withdraw")
    ).status_code == 404


@pytest.mark.usefixtures("migrated_db", "bucket", "multi_mode")
async def test_status_exposes_retention_and_privacy_url(client: AsyncClient) -> None:
    received, _ = await _apply(client)
    body = (await client.get(f"/api/v1/public/applications/{received['status_token']}")).json()
    assert body["retention_months"] == 6  # server-side default
    assert body["privacy_url"].endswith("/privacy")


@pytest.mark.usefixtures("migrated_db", "bucket", "multi_mode")
async def test_request_data_creates_task_and_activity(client: AsyncClient) -> None:
    from datetime import date, timedelta

    received, creds = await _apply(client)
    token = received["status_token"]

    resp = await client.post(f"/api/v1/public/applications/{token}/request-data")
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"status": "received"}

    assert (await client.post("/api/v1/auth/login", json=creds)).status_code == 200
    tasks = (await client.get("/api/v1/tasks")).json()
    matching = [t for t in tasks if t["title"] == "Privacy: data request — Marta Vidal"]
    assert len(matching) == 1
    assert "within one month" in matching[0]["note"]
    assert "marta-" in matching[0]["note"]  # candidate email so the admin can act
    assert matching[0]["due_date"] == (date.today() + timedelta(days=14)).isoformat()

    feed = (await client.get("/api/v1/activity")).json()
    entries = [e for e in feed if e["type"] == "candidate.data_requested"]
    assert len(entries) == 1
    assert entries[0]["payload"] == {}


@pytest.mark.usefixtures("migrated_db", "bucket", "multi_mode")
async def test_request_deletion_dedupes_open_task(client: AsyncClient) -> None:
    received, creds = await _apply(client)
    token = received["status_token"]

    assert (
        await client.post(f"/api/v1/public/applications/{token}/request-deletion")
    ).status_code == 200
    assert (
        await client.post(f"/api/v1/public/applications/{token}/request-deletion")
    ).status_code == 200

    assert (await client.post("/api/v1/auth/login", json=creds)).status_code == 200
    tasks = (await client.get("/api/v1/tasks")).json()
    matching = [t for t in tasks if t["title"] == "Privacy: deletion request — Marta Vidal"]
    assert len(matching) == 1  # second click did not stack a duplicate

    # ... but the activity trail keeps every request
    feed = (await client.get("/api/v1/activity")).json()
    assert len([e for e in feed if e["type"] == "candidate.deletion_requested"]) == 2


@pytest.mark.usefixtures("migrated_db", "bucket", "multi_mode")
async def test_privacy_requests_reject_bad_tokens(client: AsyncClient) -> None:
    assert (
        await client.post("/api/v1/public/applications/not-a-token/request-data")
    ).status_code == 404
    assert (
        await client.post("/api/v1/public/applications/not-a-token/request-deletion")
    ).status_code == 404
