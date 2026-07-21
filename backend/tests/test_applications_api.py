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

PDF_BYTES = b"%PDF-1.4 fake but good enough for a smoke"


@pytest.fixture
def multi_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "mode", "multi")


async def _publishing_company(client: AsyncClient) -> tuple[str, str]:
    """Registers a company with one published job; returns (company_slug, job_slug)."""
    name = f"Apply Co {uuid4().hex[:6]}"
    resp = await client.post(
        "/api/v1/auth/register",
        json={
            "company_name": name,
            "email": f"admin-{uuid4().hex[:8]}@vetd-ci.dev",
            "password": "a-long-secure-password",
        },
    )
    assert resp.status_code == 201, resp.text
    job = (await client.post("/api/v1/jobs", json={"title": "Backend Engineer"})).json()
    assert (await client.post(f"/api/v1/jobs/{job['id']}/publish")).status_code == 200
    await client.post("/api/v1/auth/logout")
    return name.lower().replace(" ", "-"), job["slug"]


async def _uploaded_cv(client: AsyncClient, company_slug: str, job_slug: str) -> str:
    resp = await client.post(
        f"/api/v1/public/companies/{company_slug}/jobs/{job_slug}/apply/upload-url"
    )
    assert resp.status_code == 200, resp.text
    ticket = resp.json()
    assert ticket["object_key"].startswith("cvs/")
    async with httpx.AsyncClient() as raw:
        put = await raw.put(
            ticket["upload_url"],
            content=PDF_BYTES,
            headers={"Content-Type": ticket["content_type"]},
        )
        assert put.status_code == 200, put.text
    return str(ticket["object_key"])


def _submission(object_key: str, **overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "name": "Jane Applicant",
        "email": f"jane-{uuid4().hex[:8]}@vetd-ci.dev",
        "message": "Excited to apply!",
        "github": "https://github.com/jane",
        "cv_object_key": object_key,
        "cv_filename": "jane-cv.pdf",
    }
    payload.update(overrides)
    return payload


@pytest.mark.usefixtures("migrated_db", "bucket", "multi_mode")
async def test_full_application_flow(client: AsyncClient) -> None:
    company_slug, job_slug = await _publishing_company(client)
    key = await _uploaded_cv(client, company_slug, job_slug)
    apply_url = f"/api/v1/public/companies/{company_slug}/jobs/{job_slug}/apply"

    email = f"jane-{uuid4().hex[:8]}@vetd-ci.dev"
    resp = await client.post(apply_url, json=_submission(key, email=email))
    assert resp.status_code == 201, resp.text

    # same candidate applying to the same job again → 409
    key2 = await _uploaded_cv(client, company_slug, job_slug)
    resp = await client.post(apply_url, json=_submission(key2, email=email))
    assert resp.status_code == 409


@pytest.mark.usefixtures("migrated_db", "bucket", "multi_mode")
async def test_apply_rejects_missing_or_foreign_cv(client: AsyncClient) -> None:
    company_slug, job_slug = await _publishing_company(client)
    apply_url = f"/api/v1/public/companies/{company_slug}/jobs/{job_slug}/apply"

    # nonexistent upload
    resp = await client.post(apply_url, json=_submission(f"cvs/{uuid4()}/{uuid4().hex}.pdf"))
    assert resp.status_code == 422

    # key outside the cvs/ namespace of this company
    resp = await client.post(apply_url, json=_submission("something/else.pdf"))
    assert resp.status_code == 422


@pytest.mark.usefixtures("migrated_db", "bucket", "multi_mode")
async def test_apply_rejects_oversized_cv(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    company_slug, job_slug = await _publishing_company(client)
    key = await _uploaded_cv(client, company_slug, job_slug)
    monkeypatch.setattr(settings, "cv_max_size_mb", 0)
    resp = await client.post(
        f"/api/v1/public/companies/{company_slug}/jobs/{job_slug}/apply",
        json=_submission(key),
    )
    assert resp.status_code == 422
    assert "limit" in resp.json()["detail"]


@pytest.mark.usefixtures("migrated_db", "bucket", "multi_mode")
async def test_upload_url_404s_for_unpublished_job(client: AsyncClient) -> None:
    company_slug, _ = await _publishing_company(client)
    resp = await client.post(f"/api/v1/public/companies/{company_slug}/jobs/nope/apply/upload-url")
    assert resp.status_code == 404


@pytest.mark.usefixtures("migrated_db", "bucket", "multi_mode")
async def test_apply_sends_confirmation_email(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    sent: list[dict[str, str]] = []

    def _capture(**kwargs: str) -> None:
        sent.append(kwargs)

    monkeypatch.setattr(email_service, "send_application_received", _capture)
    company_slug, job_slug = await _publishing_company(client)
    key = await _uploaded_cv(client, company_slug, job_slug)
    email = f"jane-{uuid4().hex[:8]}@vetd-ci.dev"
    resp = await client.post(
        f"/api/v1/public/companies/{company_slug}/jobs/{job_slug}/apply",
        json=_submission(key, email=email),
    )
    assert resp.status_code == 201
    assert len(sent) == 1
    assert sent[0]["to"] == email
    assert sent[0]["job_title"] == "Backend Engineer"
