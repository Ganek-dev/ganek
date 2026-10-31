"""GET /applications/{id}/email-preview: the stage mail rendered for this
candidate, byte for byte what the sender delivers (card "Candidate emails",
PR 1)."""

import re
from typing import Any
from uuid import uuid4

import pytest
from httpx import AsyncClient

from app.core.config import settings
from app.services import email as email_service
from tests.db import database_reachable, s3_reachable
from tests.helpers import upload_pdf

pytestmark = pytest.mark.skipif(
    not (database_reachable() and s3_reachable()),
    reason="database and object storage required (start postgres+minio or use CI)",
)

PDF_BYTES = b"%PDF-1.4 preview flow"


@pytest.fixture
def multi_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "mode", "multi")


async def _company_with_applicant(
    client: AsyncClient, *, with_quiz: bool = False
) -> tuple[str, str]:
    """Registers a company, publishes a job, applies as Jane. Ends logged in
    as the admin; returns (application_id, company_name)."""
    creds = {
        "email": f"admin-{uuid4().hex[:8]}@ganek-ci.dev",
        "password": "a-long-secure-password",
    }
    name = f"Preview Co {uuid4().hex[:6]}"
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
    assert (await upload_pdf(ticket, PDF_BYTES)).is_success
    resp = await client.post(
        f"{base}/apply",
        json={
            "name": "Jane Applicant",
            "email": f"cand-{uuid4().hex[:8]}@ganek-ci.dev",
            "message": "Hello!",
            "cv_object_key": ticket["object_key"],
            "cv_filename": "jane.pdf",
        },
    )
    assert resp.status_code == 201, resp.text

    assert (await client.post("/api/v1/auth/login", json=creds)).status_code == 200
    page = (await client.get(f"/api/v1/applications?job_id={job['id']}")).json()
    return page["items"][0]["id"], name


@pytest.mark.usefixtures("migrated_db", "bucket", "multi_mode")
async def test_preview_rejection_renders_for_the_candidate(client: AsyncClient) -> None:
    app_id, company_name = await _company_with_applicant(client)
    resp = await client.get(f"/api/v1/applications/{app_id}/email-preview?kind=rejection")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["kind"] == "rejection"
    assert body["subject"] == f"Your application to {company_name}"
    assert "Jane Applicant" in body["text"]
    assert "Backend Engineer" in body["text"]
    assert "</h1>" in body["html"]
    # the template part alone, what "Edit this email" prefills (PR 4)
    assert body["text"].startswith(body["body"] + "\n\nSee open positions:")


@pytest.mark.usefixtures("migrated_db", "bucket", "multi_mode")
async def test_preview_equals_the_delivered_mail(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    sent: list[dict[str, Any]] = []
    monkeypatch.setattr(email_service, "send_email", lambda **kw: sent.append(kw))
    app_id, _ = await _company_with_applicant(client)
    sent.clear()  # the apply step's "Application received" mail is not the one under test
    preview = (
        await client.get(f"/api/v1/applications/{app_id}/email-preview?kind=rejection")
    ).json()

    resp = await client.patch(
        f"/api/v1/applications/{app_id}/stage",
        json={"stage": "rejected", "notify_candidate": True},
    )
    assert resp.status_code == 200, resp.text

    assert len(sent) == 1
    assert sent[0]["subject"] == preview["subject"]
    assert sent[0]["body"] == preview["text"]
    assert sent[0]["html"] == preview["html"]


@pytest.mark.usefixtures("migrated_db", "bucket", "multi_mode")
async def test_preview_masks_the_candidate_link_and_matches_the_sent_mail_otherwise(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The status link carries a signed candidate token (withdraw, request
    data); the preview shows the link with a placeholder instead so a
    recruiter never holds the candidate's capability. Everything else is
    byte for byte the sent mail."""
    sent: list[dict[str, Any]] = []
    monkeypatch.setattr(email_service, "send_email", lambda **kw: sent.append(kw))
    app_id, _ = await _company_with_applicant(client)
    sent.clear()
    preview = (
        await client.get(f"/api/v1/applications/{app_id}/email-preview?kind=stage_advance")
    ).json()
    placeholder = re.search(r"(https?://\S+/)personal-link", preview["text"])
    assert placeholder is not None, preview["text"]
    link_prefix = placeholder.group(1)

    resp = await client.patch(
        f"/api/v1/applications/{app_id}/stage",
        json={"stage": "interview", "notify_candidate": True},
    )
    assert resp.status_code == 200, resp.text
    assert len(sent) == 1
    token = re.search(re.escape(link_prefix) + r"(\S+)", sent[0]["body"])
    assert token is not None and token.group(1) != "personal-link"
    masked_body = sent[0]["body"].replace(token.group(1), "personal-link")
    masked_html = sent[0]["html"].replace(token.group(1), "personal-link")
    assert sent[0]["subject"] == preview["subject"]
    assert masked_body == preview["text"]
    assert masked_html == preview["html"]


@pytest.mark.usefixtures("migrated_db", "bucket", "seeded_bank", "multi_mode")
async def test_preview_masks_the_quiz_link(client: AsyncClient) -> None:
    app_id, _ = await _company_with_applicant(client, with_quiz=True)
    invite = (
        await client.get(f"/api/v1/applications/{app_id}/email-preview?kind=quiz_invite")
    ).json()
    assert re.search(r"https?://\S+/personal-link", invite["text"])
    assert "/personal-link" in invite["html"]


@pytest.mark.usefixtures("migrated_db", "bucket", "multi_mode")
async def test_preview_stage_advance(client: AsyncClient) -> None:
    app_id, company_name = await _company_with_applicant(client)
    resp = await client.get(f"/api/v1/applications/{app_id}/email-preview?kind=stage_advance")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["subject"] == f"Next step: interviews at {company_name}"
    assert "Looking forward to it" in body["text"]


@pytest.mark.usefixtures("migrated_db", "bucket", "multi_mode")
async def test_preview_invite_404_without_an_attempt(client: AsyncClient) -> None:
    app_id, _ = await _company_with_applicant(client)
    for kind in ("quiz_invite", "quiz_reminder"):
        resp = await client.get(f"/api/v1/applications/{app_id}/email-preview?kind={kind}")
        assert resp.status_code == 404, resp.text
        assert resp.json()["detail"] == "No assessment to preview"


@pytest.mark.usefixtures("migrated_db", "bucket", "seeded_bank", "multi_mode")
async def test_preview_invite_and_reminder_with_a_pending_attempt(client: AsyncClient) -> None:
    app_id, _ = await _company_with_applicant(client, with_quiz=True)
    invite = await client.get(f"/api/v1/applications/{app_id}/email-preview?kind=quiz_invite")
    assert invite.status_code == 200, invite.text
    assert "Start the assessment: http" in invite.json()["text"]
    reminder = await client.get(f"/api/v1/applications/{app_id}/email-preview?kind=quiz_reminder")
    assert reminder.status_code == 200, reminder.text
    assert reminder.json()["subject"].startswith("Your assessment link expires")


@pytest.mark.usefixtures("migrated_db", "bucket", "multi_mode")
async def test_preview_rejects_unknown_kind(client: AsyncClient) -> None:
    app_id, _ = await _company_with_applicant(client)
    resp = await client.get(f"/api/v1/applications/{app_id}/email-preview?kind=message")
    assert resp.status_code == 422


@pytest.mark.usefixtures("migrated_db", "bucket", "multi_mode")
async def test_preview_is_tenant_scoped(client: AsyncClient) -> None:
    app_id, _ = await _company_with_applicant(client)
    await client.post("/api/v1/auth/logout")
    other = {
        "email": f"other-{uuid4().hex[:8]}@ganek-ci.dev",
        "password": "a-long-secure-password",
    }
    resp = await client.post(
        "/api/v1/auth/register", json={"company_name": f"Other Co {uuid4().hex[:6]}", **other}
    )
    assert resp.status_code == 201
    resp = await client.get(f"/api/v1/applications/{app_id}/email-preview?kind=rejection")
    assert resp.status_code == 404
