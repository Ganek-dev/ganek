"""Per-job stats endpoint (job overview card): applications by stage, quiz
counts, weekly series and days open, always tenant-scoped."""

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models import Application, AttemptStatus, Job, QuizAttempt
from tests.db import database_reachable, s3_reachable
from tests.helpers import upload_pdf

pytestmark = pytest.mark.skipif(
    not (database_reachable() and s3_reachable()),
    reason="database and object storage required (start postgres+minio or use CI)",
)

PDF_BYTES = b"%PDF-1.4 job stats flow"


@pytest.fixture
def multi_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "mode", "multi")


async def _company_with_applicant(client: AsyncClient) -> tuple[str, str]:
    """Registers a company, publishes a job, applies once as a candidate and
    logs back in as the admin. Returns (job_id, application_id)."""
    creds = {
        "email": f"admin-{uuid4().hex[:8]}@ganek-ci.dev",
        "password": "a-long-secure-password",
    }
    name = f"Stats Co {uuid4().hex[:6]}"
    resp = await client.post("/api/v1/auth/register", json={"company_name": name, **creds})
    assert resp.status_code == 201, resp.text
    slug = name.lower().replace(" ", "-")

    job = (await client.post("/api/v1/jobs", json={"title": "Backend Engineer"})).json()
    assert (await client.post(f"/api/v1/jobs/{job['id']}/publish")).status_code == 200
    await client.post("/api/v1/auth/logout")

    base = f"/api/v1/public/companies/{slug}/jobs/{job['slug']}"
    ticket = (await client.post(f"{base}/apply/upload-url")).json()
    assert (await upload_pdf(ticket, PDF_BYTES)).is_success
    resp = await client.post(
        f"{base}/apply",
        json={
            "name": "Marta Vidal",
            "email": f"cand-{uuid4().hex[:8]}@ganek-ci.dev",
            "cv_object_key": ticket["object_key"],
            "cv_filename": "marta.pdf",
        },
    )
    assert resp.status_code == 201, resp.text

    assert (await client.post("/api/v1/auth/login", json=creds)).status_code == 200
    application_id = (await client.get("/api/v1/applications")).json()["items"][0]["id"]
    return job["id"], application_id


async def _add_completed_attempt(
    db_session: AsyncSession, application_id: str, score: float
) -> None:
    application = await db_session.get(Application, UUID(application_id))
    assert application is not None
    now = datetime.now(UTC)
    db_session.add(
        QuizAttempt(
            company_id=application.company_id,
            application_id=application.id,
            status=AttemptStatus.COMPLETED,
            question_ids=["q1", "q2"],
            time_limit_seconds=None,
            started_at=now - timedelta(minutes=5),
            completed_at=now,
            expires_at=now + timedelta(days=7),
            score=score,
        )
    )
    await db_session.commit()


@pytest.mark.usefixtures("migrated_db", "bucket", "multi_mode")
async def test_job_stats_counts_applications_by_stage_and_quiz(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    job_id, application_id = await _company_with_applicant(client)
    await _add_completed_attempt(db_session, application_id, 0.75)

    resp = await client.get(f"/api/v1/jobs/{job_id}/stats")
    assert resp.status_code == 200, resp.text
    stats = resp.json()
    assert stats["applications"]["total"] == 1
    assert stats["applications"]["new"] == 1
    assert stats["last_30_days"] == 1
    assert stats["by_stage"] == {"new": 1}
    assert stats["quiz"]["attempts_total"] == 1
    assert stats["quiz"]["attempts_completed"] == 1
    assert stats["quiz"]["median_score"] == 0.75
    assert stats["days_open"] == 0
    assert len(stats["weekly"]) == 8
    assert stats["weekly"][-1]["count"] == 1


@pytest.mark.usefixtures("migrated_db", "bucket", "multi_mode")
async def test_job_stats_without_attempts_has_null_rates(client: AsyncClient) -> None:
    job_id, _ = await _company_with_applicant(client)
    stats = (await client.get(f"/api/v1/jobs/{job_id}/stats")).json()
    assert stats["quiz"]["attempts_total"] == 0
    assert stats["quiz"]["completion_rate"] is None
    assert stats["quiz"]["median_score"] is None


@pytest.mark.usefixtures("migrated_db", "bucket", "multi_mode")
async def test_job_stats_is_tenant_scoped(client: AsyncClient) -> None:
    job_id, _ = await _company_with_applicant(client)
    await client.post("/api/v1/auth/logout")
    resp = await client.post(
        "/api/v1/auth/register",
        json={
            "company_name": f"Other Co {uuid4().hex[:6]}",
            "email": f"admin-{uuid4().hex[:8]}@ganek-ci.dev",
            "password": "a-long-secure-password",
        },
    )
    assert resp.status_code == 201, resp.text
    assert (await client.get(f"/api/v1/jobs/{job_id}/stats")).status_code == 404


@pytest.mark.usefixtures("migrated_db", "bucket", "multi_mode")
async def test_job_stats_days_open_uses_closed_at(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    job_id, _ = await _company_with_applicant(client)
    await db_session.execute(
        update(Job)
        .where(Job.id == UUID(job_id))
        .values(published_at=datetime.now(UTC) - timedelta(days=10))
    )
    await db_session.commit()
    assert (await client.post(f"/api/v1/jobs/{job_id}/close")).status_code == 200
    stats = (await client.get(f"/api/v1/jobs/{job_id}/stats")).json()
    assert stats["days_open"] == 10
