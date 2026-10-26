"""Job page view counters (board card "Job page views", spec job posts v2
5.5, decisions JP1/JP8): one row per (job, UTC day, source), bumped from
the public job GET when the SSR sends the view headers. No identifiers."""

from datetime import UTC, date, datetime
from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models import Job, JobView
from tests.db import database_reachable

pytestmark = pytest.mark.skipif(
    not database_reachable(), reason="database required (start postgres or use CI)"
)


@pytest.fixture
def multi_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "mode", "multi")


async def _register(client: AsyncClient) -> str:
    """Registers a fresh company (the client stays logged in); returns its slug."""
    name = f"Views Co {uuid4().hex[:6]}"
    resp = await client.post(
        "/api/v1/auth/register",
        json={
            "company_name": name,
            "email": f"admin-{uuid4().hex[:8]}@ganek-ci.dev",
            "password": "a-long-secure-password",
        },
    )
    assert resp.status_code == 201, resp.text
    return name.lower().replace(" ", "-")


async def _publish(client: AsyncClient, title: str) -> dict[str, str]:
    job = (await client.post("/api/v1/jobs", json={"title": title})).json()
    resp = await client.post(f"/api/v1/jobs/{job['id']}/publish")
    assert resp.status_code == 200, resp.text
    return {"id": job["id"], "slug": job["slug"]}


async def _rows(db: AsyncSession, job_id: str) -> dict[tuple[date, str], int]:
    rows = (
        await db.execute(
            select(JobView.day, JobView.source, JobView.views).where(JobView.job_id == job_id)
        )
    ).all()
    return {(day, source): views for day, source, views in rows}


def _today() -> date:
    return datetime.now(UTC).date()


@pytest.mark.usefixtures("migrated_db", "multi_mode")
async def test_job_views_cascade_with_job(client: AsyncClient, db_session: AsyncSession) -> None:
    await _register(client)
    job = await _publish(client, "Cascade Role")
    db_session.add(JobView(job_id=job["id"], day=date(2026, 10, 1), source="direct", views=3))
    await db_session.commit()
    assert await _rows(db_session, job["id"]) == {(date(2026, 10, 1), "direct"): 3}

    await db_session.execute(delete(Job).where(Job.id == job["id"]))
    await db_session.commit()
    remaining = await db_session.scalar(
        select(func.count()).select_from(JobView).where(JobView.job_id == job["id"])
    )
    assert remaining == 0
