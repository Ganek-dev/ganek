"""Deep dependency checks behind /api/health/deep.

The shallow /api/health stays DB-free on purpose (it gates e2e
registration and the compose wait loops). This module is what an operator
or an uptime probe calls to prove Postgres, Redis and S3 are actually
reachable, and to answer "did last night's purge run?" without grepping
worker logs: the arq worker writes a heartbeat and the purge timestamp to
Redis, and the deep check reports both.
"""

import asyncio
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import anyio.to_thread
from redis import asyncio as aioredis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.services import email as email_service
from app.services import storage

WORKER_SEEN_KEY = "ganek:worker:seen_at"
LAST_PURGE_KEY = "ganek:worker:last_purge_at"
# heartbeat is a minute cron; three missed beats and the worker counts as gone
WORKER_SEEN_TTL_SECONDS = 180


@dataclass(frozen=True)
class CheckResult:
    ok: bool
    latency_ms: int
    error: str | None = None

    def as_dict(self) -> dict[str, Any]:
        body: dict[str, Any] = {"ok": self.ok, "latency_ms": self.latency_ms}
        if self.error is not None:
            body["error"] = self.error
        return body


def _elapsed_ms(started: float) -> int:
    return int((time.perf_counter() - started) * 1000)


def _describe(exc: BaseException) -> str:
    # class name only: connection errors echo hosts, ports and sometimes
    # credentials, none of which belongs in a probe response
    return exc.__class__.__name__


async def check_postgres(db: AsyncSession) -> CheckResult:
    started = time.perf_counter()
    try:
        await db.execute(text("SELECT 1"))
    except Exception as exc:  # noqa: BLE001 - any failure is the finding
        return CheckResult(False, _elapsed_ms(started), _describe(exc))
    return CheckResult(True, _elapsed_ms(started))


async def check_redis() -> tuple[CheckResult, dict[str, str | None]]:
    """Ping plus the worker's heartbeat keys.

    A fresh client per call on purpose: the rate-limit client trips a
    permanent circuit breaker on its first failure, and a health probe must
    notice Redis coming back, not just going away.
    """
    started = time.perf_counter()
    worker: dict[str, str | None] = {"seen_at": None, "last_purge_at": None}
    client = aioredis.from_url(  # type: ignore[no-untyped-call]
        settings.redis_url,
        socket_connect_timeout=1,
        socket_timeout=1,
        decode_responses=True,
    )
    try:
        await client.ping()
        seen_at, last_purge_at = await client.mget(WORKER_SEEN_KEY, LAST_PURGE_KEY)
        worker = {"seen_at": seen_at, "last_purge_at": last_purge_at}
    except Exception as exc:  # noqa: BLE001 - any failure is the finding
        return CheckResult(False, _elapsed_ms(started), _describe(exc)), worker
    finally:
        await client.aclose()
    return CheckResult(True, _elapsed_ms(started)), worker


async def check_s3() -> CheckResult:
    started = time.perf_counter()
    try:
        await anyio.to_thread.run_sync(storage.probe_bucket)
    except Exception as exc:  # noqa: BLE001 - any failure is the finding
        return CheckResult(False, _elapsed_ms(started), _describe(exc))
    return CheckResult(True, _elapsed_ms(started))


async def deep_status(db: AsyncSession) -> tuple[bool, dict[str, Any]]:
    """(healthy, body). Healthy means every infrastructure dependency
    answered; the worker fields are reported, not gated, so a stack whose
    worker is restarting still answers 200 and says so."""
    postgres, (redis, worker), s3 = await asyncio.gather(
        check_postgres(db), check_redis(), check_s3()
    )
    checks = {"postgres": postgres, "redis": redis, "s3": s3}
    failing = [name for name, result in checks.items() if not result.ok]
    body = {
        "status": "ok" if not failing else "unhealthy",
        "failing": failing,
        "checks": {name: result.as_dict() for name, result in checks.items()},
        "smtp_configured": email_service.smtp_configured(),
        "worker": worker,
        "checked_at": datetime.now(UTC).isoformat(),
    }
    return not failing, body
