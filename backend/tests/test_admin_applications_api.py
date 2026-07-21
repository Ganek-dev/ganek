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

PDF_BYTES = b"%PDF-1.4 admin flow"


@pytest.fixture
def multi_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "mode", "multi")


async def _company_with_applicant(client: AsyncClient) -> tuple[str, str]:
    """Registers a company, publishes a job, applies as a candidate.

    Ends logged in as the admin; returns (job_id, candidate_email).
    """
    creds = {
        "email": f"admin-{uuid4().hex[:8]}@vetd-ci.dev",
        "password": "a-long-secure-password",
    }
    name = f"Hire Co {uuid4().hex[:6]}"
    resp = await client.post("/api/v1/auth/register", json={"company_name": name, **creds})
    assert resp.status_code == 201, resp.text
    slug = name.lower().replace(" ", "-")

    job = (await client.post("/api/v1/jobs", json={"title": "Backend Engineer"})).json()
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
            "name": "Jane Applicant",
            "email": email,
            "message": "Hello!",
            "cv_object_key": ticket["object_key"],
            "cv_filename": "jane.pdf",
        },
    )
    assert resp.status_code == 201, resp.text

    resp = await client.post("/api/v1/auth/login", json=creds)
    assert resp.status_code == 200
    return job["id"], email


@pytest.mark.usefixtures("migrated_db", "bucket", "multi_mode")
async def test_admin_lists_and_advances_application(client: AsyncClient) -> None:
    job_id, email = await _company_with_applicant(client)

    apps = (await client.get("/api/v1/applications")).json()
    assert len(apps) == 1
    app = apps[0]
    assert app["candidate"]["email"] == email
    assert app["stage"] == "new"
    assert app["cv_filename"] == "jane.pdf"
    assert "cv_object_key" not in app  # storage internals stay internal

    # filters
    assert (await client.get(f"/api/v1/applications?job_id={job_id}")).json() != []
    assert (await client.get("/api/v1/applications?stage=rejected")).json() == []

    # stage change
    resp = await client.patch(
        f"/api/v1/applications/{app['id']}/stage", json={"stage": "screening"}
    )
    assert resp.status_code == 200
    assert resp.json()["stage"] == "screening"

    # CV download really works via the presigned URL
    resp = await client.get(f"/api/v1/applications/{app['id']}/cv-url")
    assert resp.status_code == 200
    async with httpx.AsyncClient() as raw:
        got = await raw.get(resp.json()["download_url"])
        assert got.status_code == 200
        assert got.content == PDF_BYTES
        assert 'filename="jane.pdf"' in got.headers.get("content-disposition", "")


@pytest.mark.usefixtures("migrated_db", "bucket", "multi_mode")
async def test_applications_require_auth_and_are_tenant_scoped(client: AsyncClient) -> None:
    await _company_with_applicant(client)
    target = (await client.get("/api/v1/applications")).json()[0]

    await client.post("/api/v1/auth/logout")
    assert (await client.get("/api/v1/applications")).status_code == 401

    # a different company sees nothing and cannot touch the application
    resp = await client.post(
        "/api/v1/auth/register",
        json={
            "company_name": f"Other Co {uuid4().hex[:6]}",
            "email": f"other-{uuid4().hex[:8]}@vetd-ci.dev",
            "password": "a-long-secure-password",
        },
    )
    assert resp.status_code == 201
    assert (await client.get("/api/v1/applications")).json() == []
    assert (await client.get(f"/api/v1/applications/{target['id']}")).status_code == 404
    assert (
        await client.patch(f"/api/v1/applications/{target['id']}/stage", json={"stage": "hired"})
    ).status_code == 404
    assert (await client.get(f"/api/v1/applications/{target['id']}/cv-url")).status_code == 404
