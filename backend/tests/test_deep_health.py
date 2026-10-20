"""/api/health/deep: gate, shape, and the worker bookkeeping it reports."""

from collections.abc import AsyncIterator
from typing import Any
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from app import worker
from app.core.config import settings
from app.core.security import SESSION_COOKIE_NAME, create_session_token
from app.main import app
from app.services import health
from tests.db import database_reachable, s3_reachable

needs_infra = pytest.mark.skipif(
    not (database_reachable() and s3_reachable()),
    reason="postgres + minio not reachable (start the dev stack or use CI)",
)

GREEN = health.CheckResult(ok=True, latency_ms=1)


@pytest.fixture
def all_green(monkeypatch: pytest.MonkeyPatch) -> None:
    """Infra-free happy path: every probe answers instantly."""

    async def postgres(_: Any) -> health.CheckResult:
        return GREEN

    async def redis() -> tuple[health.CheckResult, dict[str, str | None]]:
        return GREEN, {"seen_at": "2026-10-20T03:18:00+00:00", "last_purge_at": None}

    async def s3() -> health.CheckResult:
        return GREEN

    monkeypatch.setattr(health, "check_postgres", postgres)
    monkeypatch.setattr(health, "check_redis", redis)
    monkeypatch.setattr(health, "check_s3", s3)


@pytest.fixture
async def remote_client() -> AsyncIterator[AsyncClient]:
    """A client whose peer address is NOT loopback (the default test client
    is 127.0.0.1, which the gate waves through)."""
    transport = ASGITransport(app=app, client=("203.0.113.9", 4321))
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.mark.usefixtures("all_green")
async def test_loopback_peer_needs_no_session(client: AsyncClient) -> None:
    resp = await client.get("/api/health/deep")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["failing"] == []
    assert set(body["checks"]) == {"postgres", "redis", "s3"}
    assert body["worker"] == {"seen_at": "2026-10-20T03:18:00+00:00", "last_purge_at": None}
    assert body["smtp_configured"] is False
    assert resp.headers["cache-control"] == "no-store"


@pytest.mark.usefixtures("all_green")
async def test_remote_peer_without_session_is_401(remote_client: AsyncClient) -> None:
    resp = await remote_client.get("/api/health/deep")
    assert resp.status_code == 401


@pytest.mark.usefixtures("all_green")
async def test_remote_peer_with_signed_session_is_allowed(remote_client: AsyncClient) -> None:
    remote_client.cookies.set(SESSION_COOKIE_NAME, create_session_token(uuid4(), 0))
    resp = await remote_client.get("/api/health/deep")
    assert resp.status_code == 200


@pytest.mark.usefixtures("all_green")
async def test_remote_peer_with_forged_session_is_401(remote_client: AsyncClient) -> None:
    remote_client.cookies.set(SESSION_COOKIE_NAME, "not-a-signed-token")
    resp = await remote_client.get("/api/health/deep")
    assert resp.status_code == 401


async def test_failing_dependency_is_503_and_named(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def postgres(_: Any) -> health.CheckResult:
        return GREEN

    async def s3() -> health.CheckResult:
        return GREEN

    monkeypatch.setattr(health, "check_postgres", postgres)
    monkeypatch.setattr(health, "check_s3", s3)
    # real redis probe against a port nothing listens on
    monkeypatch.setattr(settings, "redis_url", "redis://127.0.0.1:1/0")
    resp = await client.get("/api/health/deep")
    assert resp.status_code == 503
    body = resp.json()
    assert body["status"] == "unhealthy"
    assert body["failing"] == ["redis"]
    assert body["checks"]["redis"]["ok"] is False
    assert "error" in body["checks"]["redis"]
    assert body["checks"]["postgres"]["ok"] is True
    assert body["worker"] == {"seen_at": None, "last_purge_at": None}


async def test_shallow_health_stays_db_free(client: AsyncClient) -> None:
    # the shallow probe must keep working with no DB at all
    resp = await client.get("/api/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


@needs_infra
@pytest.mark.usefixtures("bucket")
async def test_real_postgres_and_s3_probes(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def redis() -> tuple[health.CheckResult, dict[str, str | None]]:
        return GREEN, {"seen_at": None, "last_purge_at": None}

    monkeypatch.setattr(health, "check_redis", redis)
    resp = await client.get("/api/health/deep")
    assert resp.status_code == 200, resp.text
    checks = resp.json()["checks"]
    assert checks["postgres"]["ok"] is True
    assert checks["s3"]["ok"] is True


async def test_postgres_probe_reports_failure_without_raising() -> None:
    class BrokenSession:
        async def execute(self, _: Any) -> None:
            raise ConnectionRefusedError("down")

    result = await health.check_postgres(BrokenSession())  # type: ignore[arg-type]
    assert result.ok is False
    assert result.error == "ConnectionRefusedError"


class FakeRedis:
    def __init__(self) -> None:
        self.store: dict[str, tuple[str, int | None]] = {}

    async def set(
        self, key: str, value: str, ex: int | None = None, nx: bool = False
    ) -> bool | None:
        if nx and key in self.store:
            return None  # redis-py: SET NX on an existing key answers nil
        self.store[key] = (value, ex)
        return True


async def test_worker_heartbeat_writes_expiring_key() -> None:
    redis = FakeRedis()
    await worker.heartbeat({"redis": redis})
    value, ttl = redis.store[health.WORKER_SEEN_KEY]
    assert value.endswith("+00:00")
    assert ttl == health.WORKER_SEEN_TTL_SECONDS


async def test_worker_bookkeeping_tolerates_missing_or_broken_redis() -> None:
    await worker.heartbeat({})  # no redis in ctx (direct job calls in tests)

    class BrokenRedis:
        async def set(self, *args: Any, **kwargs: Any) -> None:
            raise ConnectionError("gone")

    await worker.heartbeat({"redis": BrokenRedis()})  # must not raise


def test_heartbeat_is_scheduled_every_minute() -> None:
    crons = [job for job in worker.WorkerSettings.cron_jobs if job.coroutine is worker.heartbeat]
    assert len(crons) == 1
    assert worker.WorkerSettings.health_check_interval == 60


@pytest.mark.skipif(not database_reachable(), reason="database not reachable")
async def test_purge_records_last_purge_at() -> None:
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from sqlalchemy.pool import NullPool

    engine = create_async_engine(settings.database_url, poolclass=NullPool)
    redis = FakeRedis()
    try:
        ctx = {
            "session_factory": async_sessionmaker(engine, expire_on_commit=False),
            "redis": redis,
        }
        await worker.purge_retention(ctx)
    finally:
        await engine.dispose()
    value, ttl = redis.store[health.LAST_PURGE_KEY]
    assert value.endswith("+00:00")
    assert ttl is None
