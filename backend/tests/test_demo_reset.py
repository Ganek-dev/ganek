"""Nightly demo reset (GANEK_DEMO_RESET_SLUG): off while unset, once per day
across workers, and a real rebuild of the demo company when it runs."""

from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app import worker
from app.core.config import settings
from app.models import Application, Company
from app.services import demo_seed
from tests.db import database_reachable, s3_reachable


class FakeRedis:
    def __init__(self) -> None:
        self.store: dict[str, tuple[str, int | None]] = {}

    async def set(
        self, key: str, value: str, ex: int | None = None, nx: bool = False
    ) -> bool | None:
        if nx and key in self.store:
            return None
        self.store[key] = (value, ex)
        return True


def _fake_ctx(redis: Any) -> dict[str, Any]:
    @asynccontextmanager
    async def session_factory() -> Any:
        yield None

    return {"session_factory": session_factory, "redis": redis}


@pytest.fixture
def seed_calls(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []

    async def fake_seed(db: Any, **kwargs: Any) -> demo_seed.SeedResult:
        calls.append(kwargs)
        return demo_seed.SeedResult(created=True, company_id=uuid4(), applications=17, attempts=11)

    monkeypatch.setattr(demo_seed, "seed", fake_seed)
    return calls


async def test_off_while_the_slug_is_unset(
    monkeypatch: pytest.MonkeyPatch, seed_calls: list[dict[str, Any]]
) -> None:
    monkeypatch.setattr(settings, "demo_reset_slug", None)
    await worker.reset_demo({})  # no session factory, no redis: must not be touched
    monkeypatch.setattr(settings, "demo_reset_slug", "")
    await worker.reset_demo({})
    assert seed_calls == []


async def test_two_workers_reset_once_per_day_with_the_configured_password(
    monkeypatch: pytest.MonkeyPatch, seed_calls: list[dict[str, Any]]
) -> None:
    monkeypatch.setattr(settings, "demo_reset_slug", "northwind")
    monkeypatch.setattr(settings, "demo_password", "s3cret-demo")
    redis = FakeRedis()
    await worker.reset_demo(_fake_ctx(redis))
    await worker.reset_demo(_fake_ctx(redis))
    assert seed_calls == [{"slug": "northwind", "password": "s3cret-demo", "reset": True}]
    today = datetime.now(UTC).date().isoformat()
    _, ttl = redis.store[f"ganek:cron:reset_demo:{today}"]
    assert ttl == worker.PURGE_CLAIM_TTL_SECONDS


async def test_default_password_when_none_is_configured(
    monkeypatch: pytest.MonkeyPatch, seed_calls: list[dict[str, Any]]
) -> None:
    monkeypatch.setattr(settings, "demo_reset_slug", "northwind")
    monkeypatch.setattr(settings, "demo_password", None)
    await worker.reset_demo(_fake_ctx(FakeRedis()))
    assert seed_calls[0]["password"] == demo_seed.DEFAULT_PASSWORD


@pytest.mark.skipif(
    not (database_reachable() and s3_reachable()),
    reason="database and object storage required (start postgres+minio or use CI)",
)
@pytest.mark.usefixtures("migrated_db", "seeded_bank", "bucket")
async def test_cron_rebuilds_the_demo_company(monkeypatch: pytest.MonkeyPatch) -> None:
    slug = f"northwind-{uuid4().hex[:6]}"
    engine = create_async_engine(settings.database_url, poolclass=NullPool)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with factory() as db:
            first = await demo_seed.seed(db, slug=slug, password="ganek-demo-1")
        monkeypatch.setattr(settings, "demo_reset_slug", slug)
        await worker.reset_demo({"session_factory": factory})  # no redis: runs anyway

        async with factory() as db:
            assert (await db.get(Company, first.company_id)) is None
            rebuilt = (await db.execute(select(Company).where(Company.slug == slug))).scalar_one()
            assert rebuilt.id != first.company_id
            count = (
                await db.execute(
                    select(func.count())
                    .select_from(Application)
                    .where(Application.company_id == rebuilt.id)
                )
            ).scalar_one()
            assert count == 17
    finally:
        await engine.dispose()
