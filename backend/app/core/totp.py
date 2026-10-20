"""TOTP second factor and recovery codes (board card A6: 2FA + session
revocation), RFC 6238 with the standard library only.

Secrets are stored Fernet-encrypted with GANEK_ENCRYPTION_KEY like the
Google credentials; recovery codes are stored as SHA-256 hashes and each
one works exactly once. Verification accepts the current 30-second step
and one step either side (clock drift), and remembers the last accepted
step so a captured code cannot be replayed inside its window.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import struct
import time
from urllib.parse import quote

ISSUER = "Ganek"
STEP_SECONDS = 30
DIGITS = 6
DRIFT_STEPS = 1
RECOVERY_CODE_COUNT = 10


def new_secret() -> str:
    """160-bit secret, base32 without padding (what authenticator apps expect)."""
    return base64.b32encode(secrets.token_bytes(20)).decode().rstrip("=")


def provisioning_uri(secret: str, *, account: str, issuer: str = ISSUER) -> str:
    """otpauth:// URI for QR codes and "enter manually" screens."""
    label = quote(f"{issuer}:{account}", safe="")
    return (
        f"otpauth://totp/{label}?secret={secret}&issuer={quote(issuer, safe='')}"
        f"&algorithm=SHA1&digits={DIGITS}&period={STEP_SECONDS}"
    )


def _code_at(secret: str, step: int) -> str:
    key = base64.b32decode(secret + "=" * (-len(secret) % 8), casefold=True)
    digest = hmac.new(key, struct.pack(">Q", step), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    number = struct.unpack(">I", digest[offset : offset + 4])[0] & 0x7FFFFFFF
    return str(number % (10**DIGITS)).zfill(DIGITS)


def current_step(now: float | None = None) -> int:
    return int((now if now is not None else time.time()) // STEP_SECONDS)


def verify_code(
    secret: str, code: str, *, last_step: int | None = None, now: float | None = None
) -> int | None:
    """The time step the code matched, or None. Steps at or before
    ``last_step`` never match again (replay inside the drift window)."""
    cleaned = "".join(ch for ch in code if ch.isdigit())
    if len(cleaned) != DIGITS:
        return None
    center = current_step(now)
    for step in range(center - DRIFT_STEPS, center + DRIFT_STEPS + 1):
        if last_step is not None and step <= last_step:
            continue
        if hmac.compare_digest(_code_at(secret, step), cleaned):
            return step
    return None


def new_recovery_codes() -> list[str]:
    """Ten codes shaped xxxxx-xxxxx (lowercase hex), shown once."""
    return [
        f"{secrets.token_hex(5)[:5]}-{secrets.token_hex(5)[:5]}" for _ in range(RECOVERY_CODE_COUNT)
    ]


def hash_recovery_code(code: str) -> str:
    normalised = code.strip().lower().replace(" ", "")
    return hashlib.sha256(normalised.encode()).hexdigest()


def consume_recovery_code(hashes: list[str], code: str) -> list[str] | None:
    """The remaining hashes after using ``code``, or None if it is not one
    of them (comparison is constant-time per entry; the list is short)."""
    candidate = hash_recovery_code(code)
    remaining = [h for h in hashes if not hmac.compare_digest(h, candidate)]
    return remaining if len(remaining) < len(hashes) else None
