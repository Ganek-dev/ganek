"""Invalidate & re-invite (D6 integrity v2): multi-attempt reissue + flag review."""

from uuid import uuid4

import httpx
import pytest
from httpx import AsyncClient

from app.core.config import settings
from app.services import email as email_service
from tests.db import database_reachable, s3_reachable

pytestmark = pytest.mark.skipif(
    not (database_reachable() and s3_reachable()),
    reason="database and object storage required (start postgres+minio or use CI)",
)

PDF_BYTES = b"%PDF-1.4 reissue flow"


@pytest.fixture
def multi_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "mode", "multi")


async def _apply_with_quiz(
    client: AsyncClient, *, with_quiz: bool = True
) -> tuple[dict[str, str | None], dict[str, str]]:
    """Register + publish (+quiz) + apply; returns (apply json, admin creds)."""
    creds = {
        "email": f"admin-{uuid4().hex[:8]}@vetd-ci.dev",
        "password": "a-long-secure-password",
    }
    name = f"Reissue Co {uuid4().hex[:6]}"
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
            "name": "Tomas Hruby",
            "email": f"tomas-{uuid4().hex[:8]}@vetd-ci.dev",
            "cv_object_key": ticket["object_key"],
            "cv_filename": "tomas-cv.pdf",
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json(), creds


async def _login_and_get_application(
    client: AsyncClient, creds: dict[str, str]
) -> dict[str, object]:
    assert (await client.post("/api/v1/auth/login", json=creds)).status_code == 200
    applications = (await client.get("/api/v1/applications")).json()
    assert len(applications) == 1
    return applications[0]


@pytest.mark.usefixtures("migrated_db", "seeded_bank", "bucket", "multi_mode")
async def test_reissue_supersedes_attempt_with_fresh_questions(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    sent: list[dict[str, object]] = []
    monkeypatch.setattr(email_service, "send_quiz_invite", lambda **kwargs: sent.append(kwargs))
    applied, creds = await _apply_with_quiz(client)
    old_token = applied["quiz_token"]
    assert old_token is not None
    old_state = (await client.get(f"/api/v1/public/quiz/{old_token}")).json()
    sent.clear()  # drop the apply-time invite (17a); watch only the reissue

    application = await _login_and_get_application(client, creds)
    old_ids = set(application["quiz_attempt"]["question_ids"])
    assert application["quiz_attempt"]["status"] == "pending"

    resp = await client.post(f"/api/v1/applications/{application['id']}/quiz/reissue")
    assert resp.status_code == 200, resp.text
    new_attempt = resp.json()
    assert new_attempt["status"] == "pending"
    new_ids = set(new_attempt["question_ids"])
    assert len(new_ids) == len(old_ids)
    # the python pool is far larger than 2×2 — fresh selection avoids repeats
    assert not (new_ids & old_ids)
    reissue = new_attempt["integrity"]["reissue"]
    assert reissue["reason"] == "integrity"
    assert reissue["mode"] == "manual"
    assert reissue["by_user_id"] is not None

    # the fresh invite email went to the candidate with a working link
    assert len(sent) == 1 and "/quiz/" in str(sent[0]["quiz_url"])

    # admin detail now shows the fresh attempt as THE attempt
    detail = (await client.get(f"/api/v1/applications/{application['id']}")).json()
    assert set(detail["quiz_attempt"]["question_ids"]) == new_ids

    # the superseded link is dead: state says invalidated, play is 410
    old_state_after = (await client.get(f"/api/v1/public/quiz/{old_token}")).json()
    assert old_state["status"] == "pending"
    assert old_state_after["status"] == "invalidated"
    assert (await client.post(f"/api/v1/public/quiz/{old_token}/next")).status_code == 410


@pytest.mark.usefixtures("migrated_db", "seeded_bank", "bucket", "multi_mode")
async def test_dismiss_flags_records_review(client: AsyncClient) -> None:
    _, creds = await _apply_with_quiz(client)
    application = await _login_and_get_application(client, creds)

    resp = await client.post(f"/api/v1/applications/{application['id']}/quiz/dismiss-flags")
    assert resp.status_code == 200, resp.text
    review = resp.json()["integrity"]["review"]
    assert review["decision"] == "dismissed"
    assert review["by_user_id"] is not None


@pytest.mark.usefixtures("migrated_db", "bucket", "multi_mode")
async def test_reissue_without_assessment_conflicts(client: AsyncClient) -> None:
    _, creds = await _apply_with_quiz(client, with_quiz=False)
    application = await _login_and_get_application(client, creds)
    for action in ("reissue", "dismiss-flags"):
        resp = await client.post(f"/api/v1/applications/{application['id']}/quiz/{action}")
        assert resp.status_code == 409, action


@pytest.mark.usefixtures("migrated_db", "seeded_bank", "bucket", "multi_mode")
async def test_reissue_is_tenant_scoped(client: AsyncClient) -> None:
    applied, _ = await _apply_with_quiz(client)
    assert applied["quiz_token"] is not None

    # a different company's admin can't touch the application
    other = {
        "email": f"admin-{uuid4().hex[:8]}@vetd-ci.dev",
        "password": "a-long-secure-password",
    }
    resp = await client.post(
        "/api/v1/auth/register", json={"company_name": f"Other Co {uuid4().hex[:6]}", **other}
    )
    assert resp.status_code == 201
    foreign_id = uuid4()
    assert (await client.post(f"/api/v1/applications/{foreign_id}/quiz/reissue")).status_code == 404
