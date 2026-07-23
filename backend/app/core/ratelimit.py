"""Fixed-window rate limiting for public endpoints.

Redis-backed so limits hold across workers/instances; falls back to an
in-process store automatically when Redis is unreachable (dev, tests).
Keys are per client IP per scope per window. Responses over the limit get
429 with a Retry-After header.
"""

import logging
import time
from collections.abc import Callable
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from fastapi import params as fastapi_params
from redis import asyncio as aioredis

from app.core.config import settings

logger = logging.getLogger(__name__)

_redis: aioredis.Redis | None = None
_redis_broken = False
_memory: dict[str, tuple[int, int]] = {}  # key -> (window, count)


def _get_redis() -> aioredis.Redis | None:
    global _redis, _redis_broken
    if _redis_broken:
        return None
    if _redis is None:
        _redis = aioredis.from_url(  # type: ignore[no-untyped-call]
            settings.redis_url, socket_connect_timeout=1, socket_timeout=1
        )
    return _redis


async def _hit_redis(key: str, seconds: int) -> int | None:
    global _redis_broken
    client = _get_redis()
    if client is None:
        return None
    try:
        async with client.pipeline(transaction=True) as pipe:
            pipe.incr(key)
            pipe.expire(key, seconds)
            count, _ = await pipe.execute()
        return int(count)
    except Exception:  # noqa: BLE001 - degrade gracefully, don't take the API down
        if not _redis_broken:
            logger.warning("redis unreachable; rate limiting falls back to per-process memory")
        _redis_broken = True
        return None


def _hit_memory(key: str, window: int) -> int:
    if len(_memory) > 10_000:  # crude bound; stale windows dominate
        _memory.clear()
    stored_window, count = _memory.get(key, (window, 0))
    if stored_window != window:
        count = 0
    _memory[key] = (window, count + 1)
    return count + 1


def client_ip(request: Request) -> str:
    """Client address; honors X-Forwarded-For when configured.

    In the standard deployment browser traffic arrives via the Next.js
    proxy, so the direct peer address would lump all users together.
    Note: XFF is spoofable when the backend port is directly reachable —
    front it with a trusted proxy in production.
    """
    if settings.trust_proxy_headers:
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


async def check_rate_limit(request: Request, scope: str, per_minute: int) -> None:
    if not settings.rate_limit_enabled or per_minute <= 0:
        return
    seconds = 60
    now = time.time()
    window = int(now // seconds)
    key = f"rl:{scope}:{client_ip(request)}:{window}"
    count = await _hit_redis(key, seconds)
    if count is None:
        count = _hit_memory(key, window)
    if count > per_minute:
        retry_after = max(1, int((window + 1) * seconds - now))
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many requests — please slow down",
            headers={"Retry-After": str(retry_after)},
        )


def rate_limit(scope: str, limit_from_settings: Callable[[], int]) -> fastapi_params.Depends:
    """Dependency factory: `dependencies=[rate_limit("auth", lambda: settings.x)]`.

    The limit is read per request so tests and operators can tune it live.
    """

    async def dependency(request: Request) -> None:
        await check_rate_limit(request, scope, limit_from_settings())

    return fastapi_params.Depends(dependency=dependency, use_cache=True)


RequestIp = Annotated[str, Depends(client_ip)]
