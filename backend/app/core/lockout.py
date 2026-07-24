"""Per-account failed-login lockout.

Complements per-IP rate limiting: this throttles attempts against a single
account regardless of source IP (distributed brute force). Redis-backed
with the same in-memory fallback as the rate limiter.
"""

import logging
import time

from app.core.config import settings
from app.core.ratelimit import _get_redis, _hit_memory, _peek_memory

logger = logging.getLogger(__name__)


def _key(email: str) -> str:
    return f"lockout:{email.lower()}"


async def is_locked(email: str) -> bool:
    if not settings.lockout_enabled:
        return False
    client = _get_redis()
    key = _key(email)
    if client is not None:
        try:
            value = await client.get(key)
            return value is not None and int(value) >= settings.lockout_max_attempts
        except Exception:  # noqa: BLE001, S110 - degrade gracefully to memory fallback
            pass
    window = int(time.time() // settings.lockout_window_seconds)
    count = _peek_memory(f"{key}:{window}", window)  # peek: must NOT increment
    return count >= settings.lockout_max_attempts


async def record_failure(email: str) -> None:
    if not settings.lockout_enabled:
        return
    client = _get_redis()
    key = _key(email)
    if client is not None:
        try:
            async with client.pipeline(transaction=True) as pipe:
                pipe.incr(key)
                pipe.expire(key, settings.lockout_window_seconds)
                await pipe.execute()
            return
        except Exception:  # noqa: BLE001, S110 - degrade gracefully to memory fallback
            pass
    window = int(time.time() // settings.lockout_window_seconds)
    _hit_memory(f"{key}:{window}", window)


async def clear(email: str) -> None:
    client = _get_redis()
    if client is not None:
        try:
            await client.delete(_key(email))
        except Exception:  # noqa: BLE001, S110 - degrade gracefully to memory fallback
            pass
