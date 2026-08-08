"""Best-effort arq enqueue. Redis being down must never break a request flow.

Jobs are self-validating (they re-check the DB at fire time), so callers
never need to abort or reschedule queued jobs — stale ones no-op.
"""

import logging
import time
from datetime import datetime

from arq import create_pool
from arq.connections import ArqRedis, RedisSettings

from app.core.config import settings

logger = logging.getLogger(__name__)

_pool: ArqRedis | None = None
# circuit breaker: after a redis failure, skip enqueue attempts for a while
# so request flows (apply, book) never stack connection timeouts
_FAILURE_BACKOFF_SECONDS = 30.0
_last_failure: float | None = None


async def _get_pool() -> ArqRedis:
    global _pool
    if _pool is None:
        redis_settings = RedisSettings.from_dsn(settings.redis_url)
        redis_settings.conn_retries = 1  # fail fast; enqueue is best-effort
        _pool = await create_pool(redis_settings)
    return _pool


async def enqueue(
    function: str,
    *args: str,
    defer_until: datetime | None = None,
    job_id: str | None = None,
) -> bool:
    """Queue a background job; False (logged) when redis is unreachable."""
    global _pool, _last_failure
    if _last_failure is not None and time.monotonic() - _last_failure < _FAILURE_BACKOFF_SECONDS:
        return False
    try:
        pool = await _get_pool()
        await pool.enqueue_job(function, *args, _defer_until=defer_until, _job_id=job_id)
        _last_failure = None
        return True
    except Exception:  # noqa: BLE001 - queueing is strictly best-effort
        logger.warning("failed to enqueue %s (redis down?)", function, exc_info=True)
        _pool = None  # a broken pool must not poison later attempts
        _last_failure = time.monotonic()
        return False
