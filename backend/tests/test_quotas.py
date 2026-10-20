"""Per-tenant abuse guards: applications/hour, emails/day, active jobs,
and the admin usage endpoint."""

from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import ratelimit
from app.core.config import settings
from app.models import ActivityLog
from app.services import activity
from tests.db import database_reachable, s3_reachable
from tests.helpers import upload_pdf

pytestmark = pytest.mark.skipif(
    not (database_reachable() and s3_reachable()),
    reason="database and object storage required (start postgres+minio or use CI)",
)

PASSWORD = "a-long-secure-password"


@pytest.fixture(autouse=True)
def _memory_counters(monkeypatch: pytest.MonkeyPatch) -> None:
    """Deterministic in-process counters (CI has no redis), multi mode,
    every guard off unless a test turns one on."""
    monkeypatch.setattr(ratelimit, "_redis_broken", True)
    ratelimit._memory.clear()
    monkeypatch.setattr(settings, "mode", "multi")
    monkeypatch.setattr(settings, "quota_emails_per_day", 0)
    monkeypatch.setattr(settings, "quota_applications_per_hour", 0)
    monkeypatch.setattr(settings, "quota_active_jobs", 0)


async def _company_with_job(client: AsyncClient) -> tuple[str, str, str, str]:
    """Registers an admin (session stays logged in) with one published job.
    Returns (company_slug, job_slug, company_id, admin_email)."""
    name = f"Quota Co {uuid4().hex[:6]}"
    admin_email = f"admin-{uuid4().hex[:8]}@ganek-ci.dev"
    resp = await client.post(
        "/api/v1/auth/register",
        json={"company_name": name, "email": admin_email, "password": PASSWORD},
    )
    assert resp.status_code == 201, resp.text
    company_id = (await client.get("/api/v1/auth/me")).json()["company_id"]
    job = (await client.post("/api/v1/jobs", json={"title": "Backend Engineer"})).json()
    assert (await client.post(f"/api/v1/jobs/{job['id']}/publish")).status_code == 200
    return name.lower().replace(" ", "-"), job["slug"], company_id, admin_email


async def _login(client: AsyncClient, email: str) -> None:
    resp = await client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
    assert resp.status_code == 200, resp.text


async def _apply(client: AsyncClient, slug: str, job_slug: str) -> int:
    base = f"/api/v1/public/companies/{slug}/jobs/{job_slug}"
    ticket = (await client.post(f"{base}/apply/upload-url")).json()
    assert (await upload_pdf(ticket)).is_success
    resp = await client.post(
        f"{base}/apply",
        json={
            "name": "Quota Candidate",
            "email": f"cand-{uuid4().hex[:8]}@ganek-ci.dev",
            "cv_object_key": ticket["object_key"],
            "cv_filename": "cv.pdf",
        },
    )
    return resp.status_code


async def _breach_entries(db: AsyncSession, company_id: str) -> int:
    result = await db.execute(
        select(func.count())
        .select_from(ActivityLog)
        .where(ActivityLog.company_id == company_id, ActivityLog.type == activity.QUOTA_EXCEEDED)
    )
    return int(result.scalar_one())


@pytest.mark.usefixtures("migrated_db", "bucket")
async def test_applications_per_hour_429_and_one_activity_entry(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "quota_applications_per_hour", 2)
    slug, job_slug, company_id, _ = await _company_with_job(client)
    await client.post("/api/v1/auth/logout")
    apply_url = f"/api/v1/public/companies/{slug}/jobs/{job_slug}/apply"
    # passes schema validation, fails the CV check inside the route (422), so
    # the guard runs on every attempt without uploading anything
    bogus = {
        "name": "Quota Probe",
        "email": "probe@ganek-ci.dev",
        "cv_object_key": f"cvs/{uuid4()}/missing.pdf",
        "cv_filename": "cv.pdf",
    }

    # every attempt counts, successful or not
    statuses = [(await client.post(apply_url, json=bogus)).status_code for _ in range(5)]
    assert statuses == [422, 422, 429, 429, 429]
    resp = await client.post(apply_url, json=bogus)
    assert resp.status_code == 429
    assert int(resp.headers["retry-after"]) >= 1
    assert "limit" in resp.json()["detail"]
    # four breaches, one activity entry for the tenant today
    assert await _breach_entries(db_session, company_id) == 1


@pytest.mark.usefixtures("migrated_db", "bucket")
async def test_email_quota_blocks_public_apply_and_shows_in_usage(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "quota_emails_per_day", 1)
    slug, job_slug, _, admin_email = await _company_with_job(client)
    await client.post("/api/v1/auth/logout")

    assert await _apply(client, slug, job_slug) == 201  # queues the first email
    assert await _apply(client, slug, job_slug) == 429  # pre-check: at the limit

    await _login(client, admin_email)
    usage = (await client.get("/api/v1/company/usage")).json()
    assert usage["emails_today"] == 1
    assert usage["emails_per_day_limit"] == 1
    assert usage["warnings"] == ["1 of 1 emails today"]


@pytest.mark.usefixtures("migrated_db", "bucket")
async def test_usage_endpoint_counts_and_warns_from_eighty_percent(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "quota_applications_per_hour", 5)
    monkeypatch.setattr(settings, "quota_active_jobs", 1)
    slug, job_slug, _, admin_email = await _company_with_job(client)
    before = (await client.get("/api/v1/company/usage")).json()
    assert before["applications_this_hour"] == 0
    assert before["active_jobs"] == 1
    assert before["warnings"] == ["1 of 1 active jobs"]

    await client.post("/api/v1/auth/logout")
    for _ in range(4):
        await _apply(client, slug, job_slug)
    await _login(client, admin_email)
    after = (await client.get("/api/v1/company/usage")).json()
    assert after["applications_this_hour"] == 4
    assert "4 of 5 applications this hour" in after["warnings"]


@pytest.mark.usefixtures("migrated_db", "bucket")
async def test_active_jobs_limit_is_409_on_publish(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "quota_active_jobs", 1)
    await _company_with_job(client)
    second = (await client.post("/api/v1/jobs", json={"title": "Second Role"})).json()
    resp = await client.post(f"/api/v1/jobs/{second['id']}/publish")
    assert resp.status_code == 409
    assert "Active job limit" in resp.json()["detail"]


@pytest.mark.usefixtures("migrated_db", "bucket")
async def test_usage_is_admin_only(client: AsyncClient) -> None:
    await client.post("/api/v1/auth/logout")
    assert (await client.get("/api/v1/company/usage")).status_code == 401
