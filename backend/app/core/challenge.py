"""Proof-of-work challenge for public forms (board card A5: CAPTCHA in
multi mode), ALTCHA v1 protocol, self-hosted.

No third party is involved, so candidate pages stay tracker-free: the
browser fetches a challenge from this server, brute-forces the number
whose hash matches (a few hundred ms of CPU in a Web Worker), and sends
the solution with the form. We recompute the hash and the HMAC, so
nothing has to be stored per challenge; a Redis mark makes a solved
challenge single-use when Redis is around.

Protocol (ALTCHA v1; the ``altcha`` widget 2.x speaks it natively and 3.x
via its v1 path, which it takes whenever the challenge JSON has a
``challenge`` key):

    salt      = <random hex>?expires=<unix ts>&
    challenge = sha256(salt + str(number))          # hex
    signature = hmac_sha256(secret, challenge)      # hex
    payload   = base64(json({algorithm, challenge, number, salt, signature}))

Off by default; ``GANEK_CAPTCHA_ENABLED=true`` plus ``GANEK_CAPTCHA_SECRET``
turn it on, and only multi mode ever shows it (single-company instances
have a closed signup and a careers page their rate limits already cover).
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import secrets
import time
from typing import Any
from urllib.parse import parse_qs

from fastapi import HTTPException, status

from app.core import ratelimit
from app.core.config import settings

logger = logging.getLogger(__name__)

ALGORITHM = "SHA-256"
SALT_BYTES = 12
REQUIRED = "captcha-required"
INVALID = "captcha-invalid"


def active() -> bool:
    """Whether public forms must carry a solved challenge right now."""
    if not settings.captcha_enabled or settings.mode != "multi":
        return False
    if not settings.captcha_secret:
        logger.warning(
            "GANEK_CAPTCHA_ENABLED is set without GANEK_CAPTCHA_SECRET; captcha stays off"
        )
        return False
    return True


def _hmac(secret: str, challenge: str) -> str:
    return hmac.new(secret.encode(), challenge.encode(), hashlib.sha256).hexdigest()


def create(*, now: float | None = None) -> dict[str, Any]:
    """A fresh challenge in the JSON shape the widget expects."""
    assert settings.captcha_secret
    expires = int((now if now is not None else time.time()) + settings.captcha_ttl_seconds)
    salt = f"{secrets.token_hex(SALT_BYTES)}?expires={expires}&"
    number = secrets.randbelow(settings.captcha_max_number + 1)
    challenge = hashlib.sha256(f"{salt}{number}".encode()).hexdigest()
    return {
        "algorithm": ALGORITHM,
        "challenge": challenge,
        "maxnumber": settings.captcha_max_number,
        "salt": salt,
        "signature": _hmac(settings.captcha_secret, challenge),
    }


def _decode(payload: str) -> dict[str, Any] | None:
    try:
        decoded = json.loads(base64.b64decode(payload, validate=True))
    except (ValueError, TypeError):
        return None
    if not isinstance(decoded, dict):
        return None
    for field in ("algorithm", "challenge", "number", "salt", "signature"):
        if field not in decoded:
            return None
    return decoded


def _expires(salt: str) -> int | None:
    _, _, query = salt.partition("?")
    values = parse_qs(query).get("expires")
    if not values:
        return None
    try:
        return int(values[0])
    except ValueError:
        return None


def verify(payload: str, *, now: float | None = None) -> bool:
    """Pure check: well-formed, unexpired, hash and HMAC both match."""
    secret = settings.captcha_secret
    if not secret:
        return False
    data = _decode(payload)
    if data is None or data["algorithm"] != ALGORITHM:
        return False
    salt = str(data["salt"])
    expires = _expires(salt)
    if expires is None or expires < (now if now is not None else time.time()):
        return False
    try:
        number = int(data["number"])
    except (TypeError, ValueError):
        return False
    if number < 0 or number > settings.captcha_max_number:
        return False
    expected = hashlib.sha256(f"{salt}{number}".encode()).hexdigest()
    return hmac.compare_digest(expected, str(data["challenge"])) and hmac.compare_digest(
        _hmac(secret, expected), str(data["signature"])
    )


async def _first_use(challenge_hash: str) -> bool:
    """SET NX the solved challenge so a captured payload cannot be replayed.
    Without Redis the check degrades to "verified once is enough": the
    payload still expires with its salt."""
    client = ratelimit._get_redis()
    if client is None:
        return True
    try:
        claimed = await client.set(
            f"ganek:captcha:{challenge_hash}", "1", nx=True, ex=settings.captcha_ttl_seconds
        )
    except Exception:  # noqa: BLE001 - same degradation as the rate limiter
        logger.warning("redis unreachable; captcha replay check skipped")
        return True
    return bool(claimed)


async def require(payload: str | None) -> None:
    """Form guard: no-op while inactive, 422 with a stable detail otherwise.

    ``captcha-required`` when the form carried no solution (the client
    shows the widget), ``captcha-invalid`` for a stale, forged or replayed
    one (the client fetches a fresh challenge and asks again).
    """
    if not active():
        return
    if not payload:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=REQUIRED)
    if not verify(payload):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=INVALID)
    data = _decode(payload)
    assert data is not None  # verify() decoded it already
    if not await _first_use(str(data["challenge"])):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=INVALID)
