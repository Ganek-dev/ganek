"""Nightly purge runs exactly once per day across workers (board card A8).

Pure: Redis and the purge are faked, the clock is frozen, two worker
contexts share one Redis the way two containers would.
"""

from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta, tzinfo
from typing import Any

import pytest

from app import worker
from app.services import retention as retention_service


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


class BrokenRedis:
    async def set(self, *args: Any, **kwargs: Any) -> None:
        raise ConnectionError("gone")


@pytest.fixture
def purge_calls(monkeypatch: pytest.MonkeyPatch) -> list[datetime]:
    calls: list[datetime] = []

    async def fake_run_purge(db: Any, *, now: datetime) -> dict[str, int]:
        calls.append(now)
        return {"applications": 0}

    monkeypatch.setattr(retention_service, "run_purge", fake_run_purge)
    return calls


def _ctx(redis: Any) -> dict[str, Any]:
    @asynccontextmanager
    async def session_factory() -> Any:
        yield None

    return {"session_factory": session_factory, "redis": redis}


def _freeze(monkeypatch: pytest.MonkeyPatch, at: datetime) -> None:
    class FrozenDatetime(datetime):
        @classmethod
        def now(cls, tz: tzinfo | None = None) -> "FrozenDatetime":  # type: ignore[override]
            return cls.fromtimestamp(at.timestamp(), tz or UTC)

    monkeypatch.setattr(worker, "datetime", FrozenDatetime)


async def test_two_workers_purge_once_per_day(
    monkeypatch: pytest.MonkeyPatch, purge_calls: list[datetime]
) -> None:
    redis = FakeRedis()
    worker_a, worker_b = _ctx(redis), _ctx(redis)
    tonight = datetime(2026, 10, 21, 3, 17, tzinfo=UTC)

    _freeze(monkeypatch, tonight)
    await worker.purge_retention(worker_a)
    await worker.purge_retention(worker_b)  # same tick, skewed by nothing
    _freeze(monkeypatch, tonight + timedelta(minutes=2))
    await worker.purge_retention(worker_b)  # skewed clock replaying the tick
    assert len(purge_calls) == 1

    _, ttl = redis.store["ganek:cron:purge_retention:2026-10-21"]
    assert ttl == worker.PURGE_CLAIM_TTL_SECONDS
    assert redis.store[worker.health_service.LAST_PURGE_KEY][0].startswith("2026-10-21T03:17")

    _freeze(monkeypatch, tonight + timedelta(days=1))
    await worker.purge_retention(worker_b)
    await worker.purge_retention(worker_a)
    assert len(purge_calls) == 2
    assert purge_calls[1].date().isoformat() == "2026-10-22"


async def test_purge_runs_without_redis_or_when_the_claim_fails(
    monkeypatch: pytest.MonkeyPatch, purge_calls: list[datetime]
) -> None:
    _freeze(monkeypatch, datetime(2026, 10, 21, 3, 17, tzinfo=UTC))
    await worker.purge_retention({"session_factory": _ctx(None)["session_factory"]})
    await worker.purge_retention(_ctx(BrokenRedis()))
    assert len(purge_calls) == 2  # a skipped purge is worse than a double one
