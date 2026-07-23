import pytest
from httpx import AsyncClient

from app.core import ratelimit
from app.core.config import settings
from tests.db import database_reachable

# the under-limit requests exercise the real login path, which needs the DB
pytestmark = pytest.mark.skipif(
    not database_reachable(), reason="database not reachable (start postgres or use CI)"
)


@pytest.fixture
def limited(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "rate_limit_enabled", True)
    monkeypatch.setattr(settings, "rate_limit_auth_per_minute", 3)
    # deterministic memory backend in tests
    monkeypatch.setattr(ratelimit, "_redis_broken", True)
    ratelimit._memory.clear()


@pytest.mark.usefixtures("limited")
async def test_auth_limit_returns_429_with_retry_after(client: AsyncClient) -> None:
    payload = {"email": "rl-test@vetd-ci.dev", "password": "definitely-wrong"}
    statuses = []
    for _ in range(4):
        resp = await client.post("/api/v1/auth/login", json=payload)
        statuses.append(resp.status_code)
    assert statuses[:3] == [401, 401, 401]  # limit of 3 consumed
    assert statuses[3] == 429
    assert int(resp.headers["retry-after"]) >= 1
    assert "slow down" in resp.json()["detail"]


@pytest.mark.usefixtures("limited")
async def test_scopes_are_independent(client: AsyncClient) -> None:
    payload = {"email": "rl-scope@vetd-ci.dev", "password": "definitely-wrong"}
    for _ in range(4):
        await client.post("/api/v1/auth/login", json=payload)
    # auth scope exhausted, but unlimited endpoints still respond
    resp = await client.get("/api/health")
    assert resp.status_code == 200


async def test_disabled_by_conftest_default(client: AsyncClient) -> None:
    # suite default: limits off — repeated calls never 429
    for _ in range(6):
        resp = await client.post(
            "/api/v1/auth/login",
            json={"email": "rl-off@vetd-ci.dev", "password": "definitely-wrong"},
        )
        assert resp.status_code == 401


def test_client_ip_honors_forwarded_header() -> None:
    class FakeRequest:
        headers = {"x-forwarded-for": "203.0.113.7, 10.0.0.1"}
        client = type("c", (), {"host": "172.18.0.3"})()

    assert ratelimit.client_ip(FakeRequest()) == "203.0.113.7"  # type: ignore[arg-type]
