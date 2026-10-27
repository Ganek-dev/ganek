"""Per-job stats endpoint (job overview card): applications by stage, quiz
counts, weekly series and days open, always tenant- and job-scoped."""

from datetime import UTC, date, datetime, time, timedelta
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models import Application, AttemptStatus, Job, JobStatus, QuizAttempt
from app.services.views import record_view
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


class Workspace:
    """One registered company: admin creds, slug, and a way to create jobs
    with applicants through the public apply flow."""

    def __init__(self, client: AsyncClient, creds: dict[str, str], slug: str) -> None:
        self.client = client
        self.creds = creds
        self.slug = slug

    async def login(self) -> None:
        resp = await self.client.post("/api/v1/auth/login", json=self.creds)
        assert resp.status_code == 200, resp.text

    async def published_job_with_applicant(
        self, title: str, *, source: str | None = None
    ) -> tuple[str, str]:
        """Creates and publishes a job, applies once as a candidate (which
        logs the admin out), logs the admin back in. Returns
        (job_id, application_id)."""
        job = (await self.client.post("/api/v1/jobs", json={"title": title})).json()
        assert (await self.client.post(f"/api/v1/jobs/{job['id']}/publish")).status_code == 200
        await self.apply(job["slug"], source=source)
        await self.login()
        page = (await self.client.get("/api/v1/applications", params={"job_id": job["id"]})).json()
        return job["id"], page["items"][0]["id"]

    async def apply(self, job_slug: str, *, source: str | None = None) -> None:
        """One public application to a published job (logs the admin out)."""
        await self.client.post("/api/v1/auth/logout")
        base = f"/api/v1/public/companies/{self.slug}/jobs/{job_slug}"
        ticket = (await self.client.post(f"{base}/apply/upload-url")).json()
        assert (await upload_pdf(ticket, PDF_BYTES)).is_success
        resp = await self.client.post(
            f"{base}/apply",
            json={
                "name": "Marta Vidal",
                "email": f"cand-{uuid4().hex[:8]}@ganek-ci.dev",
                "cv_object_key": ticket["object_key"],
                "cv_filename": "marta.pdf",
                **({"source": source} if source is not None else {}),
            },
        )
        assert resp.status_code == 201, resp.text


async def _register(client: AsyncClient) -> Workspace:
    creds = {
        "email": f"admin-{uuid4().hex[:8]}@ganek-ci.dev",
        "password": "a-long-secure-password",
    }
    name = f"Stats Co {uuid4().hex[:6]}"
    resp = await client.post("/api/v1/auth/register", json={"company_name": name, **creds})
    assert resp.status_code == 201, resp.text
    return Workspace(client, creds, name.lower().replace(" ", "-"))


async def _add_attempt(
    db_session: AsyncSession,
    application_id: str,
    *,
    status: AttemptStatus = AttemptStatus.COMPLETED,
    score: float | None = None,
    started: bool = True,
) -> None:
    application = await db_session.get(Application, UUID(application_id))
    assert application is not None
    now = datetime.now(UTC)
    completed = status is AttemptStatus.COMPLETED
    db_session.add(
        QuizAttempt(
            company_id=application.company_id,
            application_id=application.id,
            status=status,
            question_ids=["q1", "q2"],
            time_limit_seconds=None,
            started_at=now - timedelta(minutes=5) if started else None,
            completed_at=now if completed else None,
            expires_at=now + timedelta(days=7),
            score=score if completed else None,
        )
    )
    await db_session.commit()


@pytest.mark.usefixtures("migrated_db", "bucket", "multi_mode")
async def test_job_stats_counts_applications_by_stage_and_quiz(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    ws = await _register(client)
    job_id, application_id = await ws.published_job_with_applicant("Backend Engineer")
    await _add_attempt(db_session, application_id, score=0.75)

    resp = await client.get(f"/api/v1/jobs/{job_id}/stats")
    assert resp.status_code == 200, resp.text
    stats = resp.json()
    assert stats["applications"]["total"] == 1
    assert stats["applications"]["new"] == 1
    assert stats["last_30_days"] == 1
    assert stats["by_stage"] == {"new": 1}
    assert stats["quiz"]["attempts_total"] == 1
    assert stats["quiz"]["attempts_started"] == 1
    assert stats["quiz"]["attempts_completed"] == 1
    assert stats["quiz"]["median_score"] == 0.75
    assert stats["days_open"] == 0
    assert len(stats["weekly"]) == 8
    assert stats["weekly"][-1]["count"] == 1


@pytest.mark.usefixtures("migrated_db", "bucket", "multi_mode")
async def test_job_stats_are_scoped_to_the_job_not_the_company(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    ws = await _register(client)
    job_id, application_id = await ws.published_job_with_applicant("Backend Engineer")
    await _add_attempt(db_session, application_id, score=0.75)
    other_job_id, other_application_id = await ws.published_job_with_applicant("Data Engineer")
    await _add_attempt(db_session, other_application_id, score=0.25)
    resp = await client.patch(
        f"/api/v1/applications/{other_application_id}/stage",
        json={"stage": "screening", "notify_candidate": False},
    )
    assert resp.status_code == 200, resp.text

    stats = (await client.get(f"/api/v1/jobs/{job_id}/stats")).json()
    assert stats["applications"]["total"] == 1
    assert stats["by_stage"] == {"new": 1}
    assert stats["quiz"]["attempts_total"] == 1
    assert stats["quiz"]["median_score"] == 0.75
    assert stats["weekly"][-1]["count"] == 1

    other = (await client.get(f"/api/v1/jobs/{other_job_id}/stats")).json()
    assert other["by_stage"] == {"screening": 1}
    assert other["quiz"]["median_score"] == 0.25


@pytest.mark.usefixtures("migrated_db", "bucket", "multi_mode")
async def test_job_stats_quiz_denominators_skip_invalidated_and_count_started(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    ws = await _register(client)
    job_id, application_id = await ws.published_job_with_applicant("Backend Engineer")
    # a re-issue leaves the superseded attempt INVALIDATED: audit only
    await _add_attempt(db_session, application_id, status=AttemptStatus.INVALIDATED)
    # an invite never opened: issued but not started
    await _add_attempt(db_session, application_id, status=AttemptStatus.PENDING, started=False)
    await _add_attempt(db_session, application_id, score=0.5)

    quiz = (await client.get(f"/api/v1/jobs/{job_id}/stats")).json()["quiz"]
    assert quiz["attempts_total"] == 2
    assert quiz["attempts_started"] == 1
    assert quiz["attempts_completed"] == 1
    assert quiz["completion_rate"] == 0.5
    assert quiz["median_score"] == 0.5


@pytest.mark.usefixtures("migrated_db", "bucket", "multi_mode")
async def test_job_stats_without_attempts_has_null_rates(client: AsyncClient) -> None:
    ws = await _register(client)
    job_id, _ = await ws.published_job_with_applicant("Backend Engineer")
    stats = (await client.get(f"/api/v1/jobs/{job_id}/stats")).json()
    assert stats["quiz"]["attempts_total"] == 0
    assert stats["quiz"]["attempts_started"] == 0
    assert stats["quiz"]["completion_rate"] is None
    assert stats["quiz"]["median_score"] is None


@pytest.mark.usefixtures("migrated_db", "bucket", "multi_mode")
async def test_job_stats_is_tenant_scoped(client: AsyncClient) -> None:
    ws = await _register(client)
    job_id, _ = await ws.published_job_with_applicant("Backend Engineer")
    await client.post("/api/v1/auth/logout")
    await _register(client)
    assert (await client.get(f"/api/v1/jobs/{job_id}/stats")).status_code == 404


@pytest.mark.usefixtures("migrated_db", "bucket", "multi_mode")
async def test_job_stats_days_open_uses_closed_at(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    ws = await _register(client)
    job_id, _ = await ws.published_job_with_applicant("Backend Engineer")
    await db_session.execute(
        update(Job)
        .where(Job.id == UUID(job_id))
        .values(published_at=datetime.now(UTC) - timedelta(days=10))
    )
    await db_session.commit()
    assert (await client.post(f"/api/v1/jobs/{job_id}/close")).status_code == 200
    job = (await client.get(f"/api/v1/jobs/{job_id}")).json()
    assert job["closed_at"] is not None
    stats = (await client.get(f"/api/v1/jobs/{job_id}/stats")).json()
    assert stats["days_open"] == 10


@pytest.mark.usefixtures("migrated_db", "bucket", "multi_mode")
async def test_job_stats_days_open_is_null_for_closed_jobs_without_closed_at(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """Jobs closed before migration 0033 have no closed_at: the overview
    must show "-" rather than a number that grows every day."""
    ws = await _register(client)
    job_id, _ = await ws.published_job_with_applicant("Backend Engineer")
    await db_session.execute(
        update(Job)
        .where(Job.id == UUID(job_id))
        .values(
            status=JobStatus.CLOSED,
            closed_at=None,
            published_at=datetime.now(UTC) - timedelta(days=30),
        )
    )
    await db_session.commit()
    stats = (await client.get(f"/api/v1/jobs/{job_id}/stats")).json()
    assert stats["days_open"] is None


@pytest.mark.usefixtures("migrated_db", "bucket", "multi_mode")
async def test_job_stats_count_applications_by_source(client: AsyncClient) -> None:
    ws = await _register(client)
    job_id, _ = await ws.published_job_with_applicant("Backend Engineer", source="linkedin")
    job = (await client.get(f"/api/v1/jobs/{job_id}")).json()
    await ws.apply(job["slug"])  # no source: counts as direct
    await ws.apply(job["slug"], source="link:newsletter")
    await ws.login()
    stats = (await client.get(f"/api/v1/jobs/{job_id}/stats")).json()
    assert stats["by_source"] == {"linkedin": 1, "direct": 1, "link:newsletter": 1}


VIEW_HEADERS = {"X-Ganek-View": "1", "X-Ganek-Source": "linkedin"}


@pytest.mark.usefixtures("migrated_db", "bucket", "multi_mode")
async def test_job_stats_include_views_sources_and_daily_series(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    ws = await _register(client)
    job_id, _ = await ws.published_job_with_applicant("Backend Engineer", source="linkedin")
    job = (await client.get(f"/api/v1/jobs/{job_id}")).json()
    await ws.apply(job["slug"])  # no source: counts as direct
    # two counted candidate loads today, one old direct view outside the 30 days
    public_url = f"/api/v1/public/companies/{ws.slug}/jobs/{job['slug']}"
    for _ in range(2):
        assert (await client.get(public_url, headers=VIEW_HEADERS)).status_code == 200
    today = datetime.now(UTC).date()
    await record_view(db_session, UUID(job_id), "direct", day=today - timedelta(days=40))
    await ws.login()

    stats = (await client.get(f"/api/v1/jobs/{job_id}/stats")).json()
    assert stats["views"] == {"total": 3, "last_30_days": 2}
    assert stats["views_by_source"] == {"linkedin": 2, "direct": 1}
    daily = stats["daily"]
    assert len(daily) == 30
    assert [point["day"] for point in daily] == [
        (today - timedelta(days=29 - i)).isoformat() for i in range(30)
    ]
    assert daily[-1] == {"day": today.isoformat(), "views": 2, "applications": 2}
    assert daily[0] == {
        "day": (today - timedelta(days=29)).isoformat(),
        "views": 0,
        "applications": 0,
    }

    overview = (await client.get("/api/v1/stats/overview")).json()
    row = next(r for r in overview["per_job"] if r["job_id"] == job_id)
    assert row["views_30d"] == 2


@pytest.mark.usefixtures("migrated_db", "multi_mode")
async def test_per_job_views_are_tenant_scoped(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """Views join jobs on the company (stats._per_job): another company's
    views must neither appear in nor change this company's per-job totals."""
    ws_a = await _register(client)
    job = (await client.post("/api/v1/jobs", json={"title": "Viewed Role"})).json()
    assert (await client.post(f"/api/v1/jobs/{job['id']}/publish")).status_code == 200
    for _ in range(3):
        await record_view(db_session, UUID(job["id"]), "direct")
    mine = (await client.get("/api/v1/stats/overview")).json()
    assert [r["views_30d"] for r in mine["per_job"] if r["job_id"] == job["id"]] == [3]

    await _register(client)  # a second company, now signed in
    other = (await client.post("/api/v1/jobs", json={"title": "Their Role"})).json()
    assert (await client.post(f"/api/v1/jobs/{other['id']}/publish")).status_code == 200
    for _ in range(5):
        await record_view(db_session, UUID(other["id"]), "linkedin")
    theirs = (await client.get("/api/v1/stats/overview")).json()
    assert [(r["job_id"], r["views_30d"]) for r in theirs["per_job"]] == [(other["id"], 5)]
    assert (await client.get(f"/api/v1/jobs/{job['id']}/stats")).status_code == 404

    await ws_a.login()
    mine = (await client.get("/api/v1/stats/overview")).json()
    assert [(r["job_id"], r["views_30d"]) for r in mine["per_job"]] == [(job["id"], 3)]
    assert sum(r["views_30d"] for r in mine["per_job"]) == 3


def _end_of(day: date) -> datetime:
    return datetime.combine(day, time(23, 59, 59), UTC)


@pytest.mark.usefixtures("migrated_db", "bucket", "multi_mode")
async def test_job_stats_windows_are_utc_calendar_days(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """Card "Overview 30d windows": the tiles count today and the 29 (or 6)
    UTC days before it, the same days as the daily series and the views,
    never a rolling now-minus-30-days."""
    ws = await _register(client)
    job_id, today_id = await ws.published_job_with_applicant("Backend Engineer")
    job = (await client.get(f"/api/v1/jobs/{job_id}")).json()
    await ws.apply(job["slug"])
    await ws.apply(job["slug"])
    await ws.login()
    page = (await client.get("/api/v1/applications", params={"job_id": job_id})).json()
    older = [UUID(item["id"]) for item in page["items"] if item["id"] != today_id]
    assert len(older) == 2
    today = datetime.now(UTC).date()
    # one at the last second of the day 30 days ago (outside), one 7 days ago (in 30d, not 7d)
    for application_id, created_at in zip(
        older,
        (_end_of(today - timedelta(days=30)), _end_of(today - timedelta(days=7))),
        strict=True,
    ):
        await db_session.execute(
            update(Application)
            .where(Application.id == application_id)
            .values(created_at=created_at)
        )
    await db_session.commit()

    stats = (await client.get(f"/api/v1/jobs/{job_id}/stats")).json()
    assert stats["applications"]["total"] == 3
    assert stats["applications"]["last_7_days"] == 1
    assert stats["last_30_days"] == 2
    daily = stats["daily"]
    assert sum(point["applications"] for point in daily) == stats["last_30_days"]
    assert daily[-1]["applications"] == 1
    assert daily[29 - 7]["applications"] == 1
