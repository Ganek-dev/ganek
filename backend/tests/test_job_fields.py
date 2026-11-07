"""Job fields (0048): department, seniority, language, owner, internal note,
duplicate, and the opt-in auto-close on the closes-on day."""

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models import ActivityLog, Job, JobStatus
from app.services import jobs as jobs_service
from tests.db import database_reachable

pytestmark = pytest.mark.skipif(
    not database_reachable(), reason="database not reachable (start postgres or use CI)"
)


@pytest.fixture
def multi_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "mode", "multi")


async def _register(client: AsyncClient) -> tuple[str, str]:
    name = f"Fields Co {uuid4().hex[:6]}"
    resp = await client.post(
        "/api/v1/auth/register",
        json={
            "company_name": name,
            "email": f"admin-{uuid4().hex[:8]}@ganek-ci.dev",
            "password": "a-long-secure-password",
        },
    )
    assert resp.status_code == 201, resp.text
    me = (await client.get("/api/v1/auth/me")).json()
    return name.lower().replace(" ", "-"), me["id"]


def _fields(owner_id: str) -> dict[str, object]:
    return {
        "title": "Platform Engineer",
        "department": "Infrastructure",
        "seniority": "senior",
        "language": "en",
        "owner_user_id": owner_id,
        "internal_note": "Budget approved for Q1.",
    }


def test_auto_close_waits_for_the_whole_day() -> None:
    closes = datetime(2026, 11, 10, tzinfo=UTC)
    assert not jobs_service.auto_close_due(closes, closes + timedelta(hours=23, minutes=59))
    assert jobs_service.auto_close_due(closes, closes + timedelta(days=1))


@pytest.mark.usefixtures("migrated_db", "multi_mode")
async def test_fields_roundtrip_and_stay_private_where_they_should(client: AsyncClient) -> None:
    slug, me = await _register(client)
    resp = await client.post("/api/v1/jobs", json=_fields(me))
    assert resp.status_code == 201, resp.text
    job = resp.json()
    assert job["department"] == "Infrastructure"
    assert job["seniority"] == "senior"
    assert job["language"] == "en"
    assert job["owner_user_id"] == me
    assert job["internal_note"] == "Budget approved for Q1."
    assert job["auto_close"] is False

    # explicit nulls clear; text fields fall back to ""
    resp = await client.patch(
        f"/api/v1/jobs/{job['id']}",
        json={"department": None, "seniority": None, "owner_user_id": None},
    )
    assert resp.status_code == 200, resp.text
    cleared = resp.json()
    assert cleared["department"] == ""
    assert cleared["seniority"] is None
    assert cleared["owner_user_id"] is None
    assert cleared["internal_note"] == "Budget approved for Q1."  # untouched

    await client.patch(
        f"/api/v1/jobs/{job['id']}", json={"department": "Infrastructure", "seniority": "lead"}
    )
    assert (await client.post(f"/api/v1/jobs/{job['id']}/publish")).status_code == 200
    await client.post("/api/v1/auth/logout")

    page = (await client.get(f"/api/v1/public/companies/{slug}")).json()
    summary = page["jobs"][0]
    assert summary["department"] == "Infrastructure"
    assert summary["seniority"] == "lead"
    assert summary["language"] == "en"
    assert "internal_note" not in summary and "owner_user_id" not in summary

    detail = (await client.get(f"/api/v1/public/companies/{slug}/jobs/{job['slug']}")).json()
    assert detail["department"] == "Infrastructure"
    assert "internal_note" not in detail and "owner_user_id" not in detail

    feed = (await client.get(f"/api/v1/public/companies/{slug}/jobs-feed")).json()
    assert feed["jobs"][0]["department"] == "Infrastructure"
    assert feed["jobs"][0]["seniority"] == "lead"
    assert "internal_note" not in feed["jobs"][0]


@pytest.mark.usefixtures("migrated_db", "multi_mode")
async def test_bad_values_are_refused(client: AsyncClient) -> None:
    _, me = await _register(client)
    for bad in (
        {"seniority": "wizard"},
        {"language": "English"},
        {"department": "x" * 101},
        {"owner_user_id": str(uuid4())},
    ):
        resp = await client.post("/api/v1/jobs", json={**_fields(me), **bad})
        assert resp.status_code == 422, bad

    # someone from another workspace cannot be the owner
    await client.post("/api/v1/auth/logout")
    _, other = await _register(client)
    await client.post("/api/v1/auth/logout")
    await _register(client)
    resp = await client.post("/api/v1/jobs", json={"title": "X", "owner_user_id": other})
    assert resp.status_code == 422
    job = (await client.post("/api/v1/jobs", json={"title": "X"})).json()
    resp = await client.patch(f"/api/v1/jobs/{job['id']}", json={"owner_user_id": other})
    assert resp.status_code == 422


@pytest.mark.usefixtures("migrated_db", "multi_mode")
async def test_duplicate_creates_a_draft_copy(client: AsyncClient) -> None:
    _, me = await _register(client)
    payload = {
        **_fields(me),
        "closes_at": "2026-12-01",
        "auto_close": True,
        "tags": ["kubernetes"],
        "quiz_config": {"enabled": True, "tags": ["kubernetes"], "time_limit_seconds": 45},
    }
    job = (await client.post("/api/v1/jobs", json=payload)).json()
    assert job["quiz_config"]["time_limit_seconds"] == 45
    assert (await client.post(f"/api/v1/jobs/{job['id']}/publish")).status_code == 200

    resp = await client.post(f"/api/v1/jobs/{job['id']}/duplicate")
    assert resp.status_code == 201, resp.text
    copy = resp.json()
    assert copy["id"] != job["id"]
    assert copy["slug"] != job["slug"]
    assert copy["title"] == "Platform Engineer (copy)"
    assert copy["status"] == "draft"
    assert copy["published_at"] is None
    assert copy["closes_at"] is None
    assert copy["auto_close"] is False
    assert copy["quiz_config"] == job["quiz_config"]
    assert copy["screening_questions"] == job["screening_questions"]
    assert copy["scorecard_template"] == job["scorecard_template"]
    for field in ("department", "seniority", "language", "owner_user_id", "internal_note", "tags"):
        assert copy[field] == job[field], field

    # another workspace cannot duplicate it
    await client.post("/api/v1/auth/logout")
    await _register(client)
    assert (await client.post(f"/api/v1/jobs/{job['id']}/duplicate")).status_code == 404


@pytest.mark.usefixtures("migrated_db", "multi_mode")
async def test_auto_close_closes_only_opted_in_jobs_after_the_day(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _register(client)
    closes_on = "2026-11-10"

    async def make(title: str, **extra: object) -> str:
        job = (
            await client.post(
                "/api/v1/jobs", json={"title": title, "closes_at": closes_on, **extra}
            )
        ).json()
        assert (await client.post(f"/api/v1/jobs/{job['id']}/publish")).status_code == 200
        return str(job["id"])

    opted_in = await make("Opted in", auto_close=True)
    advisory = await make("Advisory only")

    day = datetime(2026, 11, 10, tzinfo=UTC)
    await jobs_service.close_expired_jobs(db_session, now=day + timedelta(hours=12))
    assert (await client.get(f"/api/v1/jobs/{opted_in}")).json()["status"] == "published"

    after = day + timedelta(days=1, minutes=5)
    await jobs_service.close_expired_jobs(db_session, now=after)
    closed = (await client.get(f"/api/v1/jobs/{opted_in}")).json()
    assert closed["status"] == "closed"
    assert closed["closed_at"] is not None
    assert (await client.get(f"/api/v1/jobs/{advisory}")).json()["status"] == "published"

    entries = (
        (await db_session.execute(select(ActivityLog).where(ActivityLog.type == "job.auto_closed")))
        .scalars()
        .all()
    )
    assert [e.payload["job_id"] for e in entries if e.payload["job_id"] == opted_in] == [opted_in]

    # a second sweep is a no-op
    await jobs_service.close_expired_jobs(db_session, now=after + timedelta(hours=1))
    row = await db_session.get(Job, UUID(opted_in))
    assert row is not None
    await db_session.refresh(row)
    assert row.status is JobStatus.CLOSED


def test_auto_close_cron_registered() -> None:
    from app import worker

    assert any(
        getattr(job, "coroutine", None) is worker.close_expired_jobs
        for job in worker.WorkerSettings.cron_jobs
    )
