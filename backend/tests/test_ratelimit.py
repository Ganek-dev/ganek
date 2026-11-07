from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from httpx import AsyncClient

from app.core import ratelimit
from app.core.config import settings
from tests.db import database_reachable

# the under-limit requests exercise the real login path, which needs the DB
pytestmark = pytest.mark.skipif(
    not database_reachable(), reason="database not reachable (start postgres or use CI)"
)


# 100 ms before a minute boundary: the worst case for a fixed-window limiter.
JUST_BEFORE_BOUNDARY = 1_700_000_040.0 - 0.1  # 1_700_000_040 is a multiple of 60


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    """Frozen clock for the limiter only. Without it a test that starts
    just before a minute boundary splits its requests across two windows
    and sees 401 where it expects 429 (PR #331 CI flake)."""
    state = SimpleNamespace(now=JUST_BEFORE_BOUNDARY)
    monkeypatch.setattr(ratelimit, "time", SimpleNamespace(time=lambda: state.now))
    return state


@pytest.fixture
def limited(monkeypatch: pytest.MonkeyPatch, clock: SimpleNamespace) -> None:
    monkeypatch.setattr(settings, "rate_limit_enabled", True)
    monkeypatch.setattr(settings, "rate_limit_auth_per_minute", 3)
    # deterministic memory backend in tests
    monkeypatch.setattr(ratelimit, "_redis_broken", True)
    ratelimit._memory.clear()


@pytest.mark.usefixtures("limited")
async def test_auth_limit_returns_429_with_retry_after(client: AsyncClient) -> None:
    payload = {"email": "rl-test@ganek-ci.dev", "password": "definitely-wrong"}
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
    payload = {"email": "rl-scope@ganek-ci.dev", "password": "definitely-wrong"}
    for _ in range(4):
        await client.post("/api/v1/auth/login", json=payload)
    # auth scope exhausted, but unlimited endpoints still respond
    resp = await client.get("/api/health")
    assert resp.status_code == 200


class _FakeRequest:
    headers: dict[str, str] = {}
    client = SimpleNamespace(host="198.51.100.9")


@pytest.mark.usefixtures("limited")
async def test_limit_holds_across_slow_requests_before_boundary(clock: SimpleNamespace) -> None:
    # requests spread over the last 100 ms of a window all count in that window
    request = _FakeRequest()
    for step in range(3):
        clock.now = JUST_BEFORE_BOUNDARY + step * 0.03
        await ratelimit.check_rate_limit(request, "auth", 3)  # type: ignore[arg-type]
    clock.now = JUST_BEFORE_BOUNDARY + 0.09
    with pytest.raises(HTTPException) as exc:
        await ratelimit.check_rate_limit(request, "auth", 3)  # type: ignore[arg-type]
    assert exc.value.status_code == 429
    assert exc.value.headers == {"Retry-After": "1"}


@pytest.mark.usefixtures("limited")
async def test_window_resets_after_boundary(clock: SimpleNamespace) -> None:
    # documents the root cause: crossing the boundary starts a fresh count
    request = _FakeRequest()
    for _ in range(3):
        await ratelimit.check_rate_limit(request, "auth", 3)  # type: ignore[arg-type]
    clock.now = JUST_BEFORE_BOUNDARY + 0.2
    await ratelimit.check_rate_limit(request, "auth", 3)  # type: ignore[arg-type]


async def test_disabled_by_conftest_default(client: AsyncClient) -> None:
    # suite default: limits off - repeated calls never 429
    for _ in range(6):
        resp = await client.post(
            "/api/v1/auth/login",
            json={"email": "rl-off@ganek-ci.dev", "password": "definitely-wrong"},
        )
        assert resp.status_code == 401


def test_client_ip_honors_forwarded_header() -> None:
    class FakeRequest:
        headers = {"x-forwarded-for": "203.0.113.7, 10.0.0.1"}
        client = type("c", (), {"host": "172.18.0.3"})()

    assert ratelimit.client_ip(FakeRequest()) == "203.0.113.7"  # type: ignore[arg-type]
