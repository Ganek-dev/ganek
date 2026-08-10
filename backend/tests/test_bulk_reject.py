"""Bulk reject: stage transitions, tenant scope, cap, activity, optional emails."""

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

PDF_BYTES = b"%PDF-1.4 bulk reject flow"


@pytest.fixture
def multi_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "mode", "multi")


async def _register_company(client: AsyncClient, name_prefix: str) -> dict[str, str]:
    creds = {
        "email": f"admin-{uuid4().hex[:8]}@vetd-ci.dev",
        "password": "a-long-secure-password",
    }
    name = f"{name_prefix} {uuid4().hex[:6]}"
    resp = await client.post("/api/v1/auth/register", json={"company_name": name, **creds})
    assert resp.status_code == 201, resp.text
    return creds


async def _company_with_applicants(
    client: AsyncClient, n: int, *, name_prefix: str = "Bulk Co"
) -> tuple[list[dict[str, str]], dict[str, str]]:
    """Registers a company, publishes a job, applies n candidates.

    Ends logged in as the admin. Returns (applicants, admin_creds) where
    applicants is [{"email": ..., "status_token": ...}, ...] in apply order.
    """
    creds = {
        "email": f"admin-{uuid4().hex[:8]}@vetd-ci.dev",
        "password": "a-long-secure-password",
    }
    name = f"{name_prefix} {uuid4().hex[:6]}"
    resp = await client.post("/api/v1/auth/register", json={"company_name": name, **creds})
    assert resp.status_code == 201, resp.text
    slug = name.lower().replace(" ", "-")

    job = (await client.post("/api/v1/jobs", json={"title": "Backend Engineer"})).json()
    assert (await client.post(f"/api/v1/jobs/{job['id']}/publish")).status_code == 200
    await client.post("/api/v1/auth/logout")

    base = f"/api/v1/public/companies/{slug}/jobs/{job['slug']}"
    applicants: list[dict[str, str]] = []
    for _ in range(n):
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
                "name": "Jane Applicant",
                "email": email,
                "cv_object_key": ticket["object_key"],
                "cv_filename": "jane.pdf",
            },
        )
        assert resp.status_code == 201, resp.text
        applicants.append({"email": email, "status_token": resp.json()["status_token"]})

    resp = await client.post("/api/v1/auth/login", json=creds)
    assert resp.status_code == 200
    return applicants, creds


async def _ids_by_email(client: AsyncClient) -> dict[str, str]:
    apps = (await client.get("/api/v1/applications")).json()
    return {a["candidate"]["email"]: a["id"] for a in apps}


@pytest.mark.usefixtures("migrated_db", "bucket", "multi_mode")
async def test_bulk_reject_sets_stage_and_reports_counts(client: AsyncClient) -> None:
    applicants, _ = await _company_with_applicants(client, 3)
    ids = await _ids_by_email(client)
    a, b, c = (ids[app["email"]] for app in applicants)

    resp = await client.post("/api/v1/applications/bulk-reject", json={"application_ids": [a, b]})
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"rejected": 2, "skipped": 0}

    stages = {app["id"]: app["stage"] for app in (await client.get("/api/v1/applications")).json()}
    assert stages[a] == "rejected"
    assert stages[b] == "rejected"
    assert stages[c] == "new"


@pytest.mark.usefixtures("migrated_db", "bucket", "multi_mode")
async def test_bulk_reject_skips_rejected_withdrawn_foreign_unknown(client: AsyncClient) -> None:
    applicants, creds = await _company_with_applicants(client, 3)
    ids = await _ids_by_email(client)
    already_rejected, withdrawn, untouched = (ids[app["email"]] for app in applicants)

    resp = await client.patch(
        f"/api/v1/applications/{already_rejected}/stage", json={"stage": "rejected"}
    )
    assert resp.status_code == 200

    withdrawn_token = applicants[1]["status_token"]
    await client.post("/api/v1/auth/logout")
    resp = await client.post(f"/api/v1/public/applications/{withdrawn_token}/withdraw")
    assert resp.status_code == 200
    assert (await client.post("/api/v1/auth/login", json=creds)).status_code == 200

    foreign_applicants, foreign_creds = await _company_with_applicants(
        client, 1, name_prefix="Foreign Co"
    )
    foreign_id = (await _ids_by_email(client))[foreign_applicants[0]["email"]]
    await client.post("/api/v1/auth/logout")
    assert (await client.post("/api/v1/auth/login", json=creds)).status_code == 200

    random_id = str(uuid4())

    resp = await client.post(
        "/api/v1/applications/bulk-reject",
        json={"application_ids": [already_rejected, withdrawn, foreign_id, random_id]},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"rejected": 0, "skipped": 4}

    stages = {app["id"]: app["stage"] for app in (await client.get("/api/v1/applications")).json()}
    assert stages[withdrawn] == "withdrawn"
    assert stages[untouched] == "new"

    feed = (await client.get("/api/v1/activity")).json()
    assert not any(row["type"] == "applications.bulk_rejected" for row in feed)

    await client.post("/api/v1/auth/logout")
    assert (await client.post("/api/v1/auth/login", json=foreign_creds)).status_code == 200
    foreign_stages = {
        app["id"]: app["stage"] for app in (await client.get("/api/v1/applications")).json()
    }
    assert foreign_stages[foreign_id] == "new"


@pytest.mark.usefixtures("migrated_db", "bucket", "multi_mode")
async def test_bulk_reject_cap(client: AsyncClient) -> None:
    await _register_company(client, "Cap Co")
    ids = [str(uuid4()) for _ in range(101)]
    resp = await client.post("/api/v1/applications/bulk-reject", json={"application_ids": ids})
    assert resp.status_code == 422


@pytest.mark.usefixtures("migrated_db", "bucket", "multi_mode")
async def test_bulk_reject_emails_only_when_asked(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.services import email as email_service

    rejections: list[dict[str, object]] = []
    monkeypatch.setattr(email_service, "send_rejection", lambda **kw: rejections.append(kw))

    applicants, _ = await _company_with_applicants(client, 3)
    ids = await _ids_by_email(client)
    a, b, c = (ids[app["email"]] for app in applicants)

    resp = await client.post("/api/v1/applications/bulk-reject", json={"application_ids": [a, b]})
    assert resp.status_code == 200
    assert resp.json() == {"rejected": 2, "skipped": 0}
    assert rejections == []

    resp = await client.post(
        "/api/v1/applications/bulk-reject",
        json={"application_ids": [a, b, c], "notify_candidates": True},
    )
    assert resp.status_code == 200
    assert resp.json() == {"rejected": 1, "skipped": 2}
    assert len(rejections) == 1
    assert rejections[0]["to"] == applicants[2]["email"]
    assert rejections[0]["completed_assessment"] is False

    resp = await client.post(
        "/api/v1/applications/bulk-reject",
        json={"application_ids": [a, b, c], "notify_candidates": True},
    )
    assert resp.status_code == 200
    assert resp.json() == {"rejected": 0, "skipped": 3}
    assert len(rejections) == 1


@pytest.mark.usefixtures("migrated_db", "bucket", "multi_mode")
async def test_bulk_reject_records_one_activity_entry(client: AsyncClient) -> None:
    applicants, _ = await _company_with_applicants(client, 2)
    ids = await _ids_by_email(client)
    a, b = (ids[app["email"]] for app in applicants)

    resp = await client.post("/api/v1/applications/bulk-reject", json={"application_ids": [a, b]})
    assert resp.status_code == 200
    assert resp.json() == {"rejected": 2, "skipped": 0}

    feed = (await client.get("/api/v1/activity")).json()
    bulk_entries = [row for row in feed if row["type"] == "applications.bulk_rejected"]
    assert len(bulk_entries) == 1
    assert bulk_entries[0]["payload"] == {"count": 2}
