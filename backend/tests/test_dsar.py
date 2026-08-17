"""DSAR export (Art. 15/20): full candidate bundle, admin-mediated.

The bundle is destined FOR the candidate, so recruiter identifiers are
third-party data and must be scrubbed (reissue/review by_user_id, note
authors) — and bank secrets (correct_key) must never appear.
"""

import json
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

PDF_BYTES = b"%PDF-1.4 dsar flow"
PASSWORD = "a-long-secure-password"


@pytest.fixture
def multi_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "mode", "multi")


async def _company_with_completed_quiz(
    client: AsyncClient,
) -> tuple[str, str, dict[str, str]]:
    """Register + publish quiz job + apply + complete the quiz.

    Ends logged in as the admin; returns (application_id, candidate_email, creds).
    """
    creds = {"email": f"admin-{uuid4().hex[:8]}@vetd-ci.dev", "password": PASSWORD}
    name = f"Dsar Co {uuid4().hex[:6]}"
    resp = await client.post("/api/v1/auth/register", json={"company_name": name, **creds})
    assert resp.status_code == 201, resp.text
    slug = name.lower().replace(" ", "-")
    job = (
        await client.post(
            "/api/v1/jobs",
            json={
                "title": "Py Dev",
                "tags": ["python"],
                "quiz_config": {"enabled": True, "question_count": 2},
            },
        )
    ).json()
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
    email = f"cand-{uuid4().hex[:8]}@vetd-ci.dev"
    resp = await client.post(
        f"{base}/apply",
        json={
            "name": "Dana Subject",
            "email": email,
            "message": "I love writing Python.",
            "cv_object_key": ticket["object_key"],
            "cv_filename": "dana.pdf",
        },
    )
    assert resp.status_code == 201, resp.text
    quiz_token = resp.json()["quiz_token"]
    assert quiz_token is not None
    while True:
        body = (await client.post(f"/api/v1/public/quiz/{quiz_token}/next")).json()
        if body["done"]:
            break
        question = body["question"]
        await client.post(
            f"/api/v1/public/quiz/{quiz_token}/answer",
            json={"question_id": question["id"], "answer_key": question["options"][0]["key"]},
        )

    assert (await client.post("/api/v1/auth/login", json=creds)).status_code == 200
    app_id = (await client.get("/api/v1/applications")).json()["items"][0]["id"]
    return app_id, email, creds


@pytest.mark.usefixtures("migrated_db", "seeded_bank", "bucket", "multi_mode")
async def test_dsar_bundle_contents_and_third_party_scrub(client: AsyncClient) -> None:
    app_id, email, creds = await _company_with_completed_quiz(client)

    # recruiter opinion + a reissue (stamps integrity.reissue with by_user_id)
    resp = await client.post(
        f"/api/v1/applications/{app_id}/notes", json={"body": "Sharp take-home answers."}
    )
    assert resp.status_code == 201
    assert (await client.post(f"/api/v1/applications/{app_id}/quiz/reissue")).status_code == 200

    resp = await client.get(f"/api/v1/applications/{app_id}/dsar-export")
    assert resp.status_code == 200, resp.text
    bundle = resp.json()

    assert bundle["candidate"]["email"] == email
    assert bundle["candidate"]["name"] == "Dana Subject"
    assert bundle["controller"]["privacy_notice_url"].endswith("/privacy")

    assert len(bundle["applications"]) == 1
    application = bundle["applications"][0]
    assert application["job_title"] == "Py Dev"
    assert application["message"] == "I love writing Python."
    assert application["cv_filename"] == "dana.pdf"
    assert application["cv_download_url"].startswith("http")

    # both attempts are in the bundle: the invalidated (scored) one + the reissue
    attempts = application["quiz_attempts"]
    assert len(attempts) == 2
    scored = next(a for a in attempts if a["score"] is not None)
    assert len(scored["answers"]) == 2
    assert all("answer_key" in a and "is_correct" in a for a in scored["answers"])
    fresh = next(a for a in attempts if a["score"] is None)
    assert fresh["integrity"].get("reissue", {}).get("reason") == "integrity"

    assert [n["body"] for n in application["notes"]] == ["Sharp take-home answers."]
    assert {e["type"] for e in application["activity"]} >= {"application.received"}

    # third-party + secret scrub over the whole serialized bundle
    dump = json.dumps(bundle)
    assert "correct_key" not in dump
    assert "by_user_id" not in dump
    assert creds["email"] not in dump  # note author / reissuer identity stays out
    assert "author" not in dump


@pytest.mark.usefixtures("migrated_db", "seeded_bank", "bucket", "multi_mode")
async def test_dsar_is_admin_only_and_tenant_scoped(client: AsyncClient) -> None:
    app_id, _, _ = await _company_with_completed_quiz(client)

    member = {"email": f"member-{uuid4().hex[:8]}@vetd-ci.dev", "password": PASSWORD}
    assert (
        await client.post("/api/v1/users", json={**member, "role": "member"})
    ).status_code == 201
    await client.post("/api/v1/auth/logout")
    assert (await client.post("/api/v1/auth/login", json=member)).status_code == 200
    assert (await client.get(f"/api/v1/applications/{app_id}/dsar-export")).status_code == 403

    await client.post("/api/v1/auth/logout")
    resp = await client.post(
        "/api/v1/auth/register",
        json={
            "company_name": f"Nosy Co {uuid4().hex[:6]}",
            "email": f"nosy-{uuid4().hex[:8]}@vetd-ci.dev",
            "password": PASSWORD,
        },
    )
    assert resp.status_code == 201
    assert (await client.get(f"/api/v1/applications/{app_id}/dsar-export")).status_code == 404
