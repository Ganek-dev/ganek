"""Job page view counters (board card "Job page views", spec job posts v2
5.5, decisions JP1/JP8): one row per (job, UTC day, source), bumped from
the public job GET when the SSR sends the view headers. No identifiers."""

import asyncio
from datetime import UTC, date, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

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


VIEW = {"X-Ganek-View": "1"}


async def _view(
    client: AsyncClient,
    slug: str,
    job_slug: str,
    headers: dict[str, str] | None = None,
    **params: str,
) -> int:
    """One public GET of the job detail, as a candidate would make it."""
    await client.post("/api/v1/auth/logout")
    resp = await client.get(
        f"/api/v1/public/companies/{slug}/jobs/{job_slug}", headers=headers, params=params
    )
    return resp.status_code


async def _preview_token(client: AsyncClient, job_id: str) -> str:
    resp = await client.post(f"/api/v1/jobs/{job_id}/preview-link")
    assert resp.status_code == 200, resp.text
    return str(resp.json()["url"].split("preview=")[1])


@pytest.mark.usefixtures("migrated_db", "multi_mode")
async def test_view_header_increments_one_row_per_day_and_source(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    slug = await _register(client)
    job = await _publish(client, "Counted Role")
    linkedin = {**VIEW, "X-Ganek-Source": "linkedin"}
    assert await _view(client, slug, job["slug"], linkedin) == 200
    assert await _view(client, slug, job["slug"], linkedin) == 200
    assert (
        await _view(client, slug, job["slug"], {**VIEW, "X-Ganek-Source": "link:newsletter"}) == 200
    )
    assert await _rows(db_session, job["id"]) == {
        (_today(), "linkedin"): 2,
        (_today(), "link:newsletter"): 1,
    }


@pytest.mark.usefixtures("migrated_db", "multi_mode")
async def test_plain_get_and_wrong_header_value_do_not_count(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    slug = await _register(client)
    job = await _publish(client, "Quiet Role")
    assert await _view(client, slug, job["slug"]) == 200
    assert (
        await _view(client, slug, job["slug"], {"X-Ganek-View": "yes", "X-Ganek-Source": "x"})
        == 200
    )
    assert await _view(client, slug, job["slug"], {"X-Ganek-Source": "google"}) == 200
    assert await _rows(db_session, job["id"]) == {}
    # the view header alone counts, as direct
    assert await _view(client, slug, job["slug"], VIEW) == 200
    assert await _rows(db_session, job["id"]) == {(_today(), "direct"): 1}


@pytest.mark.usefixtures("migrated_db", "multi_mode")
async def test_invalid_source_counts_as_direct(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    slug = await _register(client)
    job = await _publish(client, "Junk Source Role")
    for junk in (
        "<script>alert(1)</script>",
        "other",
        "ref:evil.example/path?x=1",
        "link:" + "a" * 41,
    ):
        assert await _view(client, slug, job["slug"], {**VIEW, "X-Ganek-Source": junk}) == 200
    assert await _rows(db_session, job["id"]) == {(_today(), "direct"): 4}


@pytest.mark.usefixtures("migrated_db", "multi_mode")
async def test_preview_and_unpublished_never_count(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    slug = await _register(client)
    draft = (await client.post("/api/v1/jobs", json={"title": "Draft Role"})).json()
    draft_token = await _preview_token(client, draft["id"])
    live = await _publish(client, "Live Role")
    live_token = await _preview_token(client, live["id"])
    headers = {**VIEW, "X-Ganek-Source": "linkedin"}
    assert await _view(client, slug, draft["slug"], headers, preview=draft_token) == 200
    assert await _view(client, slug, draft["slug"], headers) == 404
    assert await _view(client, slug, live["slug"], headers, preview=live_token) == 200
    assert await _rows(db_session, draft["id"]) == {}
    assert await _rows(db_session, live["id"]) == {}
    # the same live job without a token counts
    assert await _view(client, slug, live["slug"], headers) == 200
    assert await _rows(db_session, live["id"]) == {(_today(), "linkedin"): 1}


@pytest.mark.usefixtures("migrated_db", "multi_mode")
async def test_fold_after_fifty_distinct_sources(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    from app.services.views import MAX_SOURCES_PER_DAY, OTHER, record_view

    await _register(client)
    job = await _publish(client, "Spammed Role")
    job_id = UUID(job["id"])
    for i in range(MAX_SOURCES_PER_DAY):
        assert await record_view(db_session, job_id, f"link:s{i}") == f"link:s{i}"
    assert await record_view(db_session, job_id, "link:s50") == OTHER
    assert await record_view(db_session, job_id, "link:s51") == OTHER
    assert await record_view(db_session, job_id, "link:s0") == "link:s0"
    rows = await _rows(db_session, job["id"])
    assert len(rows) == MAX_SOURCES_PER_DAY + 1
    assert rows[(_today(), OTHER)] == 2
    assert rows[(_today(), "link:s0")] == 2
    # another day starts a fresh budget
    yesterday = _today() - timedelta(days=1)
    assert await record_view(db_session, job_id, "link:s50", day=yesterday) == "link:s50"


@pytest.mark.usefixtures("migrated_db", "multi_mode")
async def test_view_source_never_yields_other() -> None:
    from app.services.views import view_source

    assert view_source(None) == "direct"
    assert view_source("other") == "direct"
    assert view_source(" LinkedIn ") == "linkedin"
    assert view_source("link:newsletter") == "link:newsletter"


async def test_record_view_task_never_raises() -> None:
    from sqlalchemy.ext.asyncio import create_async_engine

    from app.services.views import record_view_task

    dead = create_async_engine("postgresql+asyncpg://nobody:nothing@127.0.0.1:1/none")
    assert await record_view_task(dead, uuid4(), "direct") is None
    await dead.dispose()


@pytest.mark.usefixtures("migrated_db", "multi_mode")
async def test_fold_never_swallows_known_buckets_or_direct(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """Review focus 2: a spam run must not push real traffic into 'other'."""
    from app.services.views import MAX_SOURCES_PER_DAY, OTHER, record_view

    slug = await _register(client)
    job = await _publish(client, "Spam Then Real Role")
    job_id = UUID(job["id"])
    for i in range(MAX_SOURCES_PER_DAY + 10):
        await record_view(db_session, job_id, f"link:spam{i}")
    assert await _view(client, slug, job["slug"], {**VIEW, "X-Ganek-Source": "<script>"}) == 200
    assert await _view(client, slug, job["slug"], {**VIEW, "X-Ganek-Source": "linkedin"}) == 200
    assert await record_view(db_session, job_id, "ref:late.example") == OTHER
    rows = await _rows(db_session, job["id"])
    assert rows[(_today(), "direct")] == 1
    assert rows[(_today(), "linkedin")] == 1
    assert rows[(_today(), OTHER)] == 11
    named_links = [s for (_, s) in rows if s.startswith("link:")]
    assert len(named_links) == MAX_SOURCES_PER_DAY


@pytest.mark.usefixtures("migrated_db", "multi_mode")
async def test_concurrent_views_never_overshoot_the_source_budget(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """Card "Views: atomic fold budget": the budget check and the upsert
    serialise per (job, day), so twenty tasks racing at 49 names add exactly
    one name and fold the other nineteen into 'other'."""
    from app.services.views import MAX_SOURCES_PER_DAY, OTHER, record_view

    await _register(client)
    job = await _publish(client, "Raced Role")
    job_id = UUID(job["id"])
    for i in range(MAX_SOURCES_PER_DAY - 1):
        assert await record_view(db_session, job_id, f"link:s{i}") == f"link:s{i}"

    engine = create_async_engine(settings.database_url, poolclass=NullPool)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async def race(name: str) -> str:
        async with factory() as db:
            return await record_view(db, job_id, name)

    try:
        labels = await asyncio.gather(*(race(f"link:new{i}") for i in range(20)))
    finally:
        await engine.dispose()

    assert labels.count(OTHER) == 19
    assert len([label for label in labels if label.startswith("link:new")]) == 1
    rows = await _rows(db_session, job["id"])
    named = [s for (_, s) in rows if s.startswith("link:")]
    assert len(named) == MAX_SOURCES_PER_DAY
    assert rows[(_today(), OTHER)] == 19


@pytest.mark.usefixtures("migrated_db", "multi_mode")
async def test_ssr_secret_gates_counting_when_set(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Card "Hardening: optional GANEK_SSR_SECRET": with the secret set, a
    request is served either way but counts only when it carries the secret."""
    monkeypatch.setattr(settings, "ssr_secret", "shared-with-the-ssr")
    slug = await _register(client)
    job = await _publish(client, "Gated Role")
    assert await _view(client, slug, job["slug"], VIEW) == 200
    assert await _view(client, slug, job["slug"], {**VIEW, "X-Ganek-SSR-Secret": "wrong"}) == 200
    assert await _rows(db_session, job["id"]) == {}
    signed = {**VIEW, "X-Ganek-SSR-Secret": "shared-with-the-ssr", "X-Ganek-Source": "linkedin"}
    assert await _view(client, slug, job["slug"], signed) == 200
    assert await _rows(db_session, job["id"]) == {(_today(), "linkedin"): 1}


@pytest.mark.usefixtures("migrated_db", "multi_mode")
async def test_without_ssr_secret_the_header_is_ignored(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Unset (the default): behaviour unchanged, a stray secret header is noise."""
    monkeypatch.setattr(settings, "ssr_secret", None)
    slug = await _register(client)
    job = await _publish(client, "Open Role")
    assert await _view(client, slug, job["slug"], {**VIEW, "X-Ganek-SSR-Secret": "anything"}) == 200
    assert await _view(client, slug, job["slug"], VIEW) == 200
    assert await _rows(db_session, job["id"]) == {(_today(), "direct"): 2}
