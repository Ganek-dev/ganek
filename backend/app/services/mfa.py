"""Second factor lifecycle and "sign out everywhere" (board card A6).

Enrolment is two-step: ``begin`` stores a fresh (encrypted) secret with
``totp_enabled_at`` still NULL, ``confirm`` proves the authenticator has
it and turns it on, handing out the recovery codes exactly once. Login
asks for a code only when ``enabled``; wrong codes feed the same
per-account lockout as passwords, under their own key.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.core import lockout, totp
from app.core.crypto import decrypt_secret, encrypt_secret
from app.models import User


class MfaError(Exception):
    pass


class NotEnrolledError(MfaError):
    pass


class WrongCodeError(MfaError):
    pass


class MfaLockedError(MfaError):
    pass


def enabled(user: User) -> bool:
    return user.totp_enabled_at is not None and user.totp_secret is not None


def _lockout_key(user: User) -> str:
    return f"mfa:{user.email}"


def _secret(user: User) -> str:
    if user.totp_secret is None:
        raise NotEnrolledError
    plain = decrypt_secret(user.totp_secret)
    if plain is None:  # key rotated underneath us: the factor is unusable
        raise NotEnrolledError
    return plain


async def begin(db: AsyncSession, user: User) -> tuple[str, str]:
    """New pending secret (replaces any unconfirmed one). Returns
    (secret, otpauth URI) for the authenticator app."""
    if enabled(user):
        raise MfaError("already enabled")
    secret = totp.new_secret()
    user.totp_secret = encrypt_secret(secret)
    user.totp_last_step = None
    user.recovery_codes = None
    await db.commit()
    return secret, totp.provisioning_uri(secret, account=user.email)


async def confirm(db: AsyncSession, user: User, code: str) -> list[str]:
    """Turn the factor on once the app shows a valid code; returns the
    recovery codes, shown to the user this one time."""
    if enabled(user):
        raise MfaError("already enabled")
    step = totp.verify_code(_secret(user), code)
    if step is None:
        raise WrongCodeError
    codes = totp.new_recovery_codes()
    user.totp_enabled_at = datetime.now(UTC)
    user.totp_last_step = step
    user.recovery_codes = [totp.hash_recovery_code(c) for c in codes]
    await db.commit()
    return codes


async def disable(db: AsyncSession, user: User) -> None:
    """Caller has already re-authenticated (password or a valid code)."""
    user.totp_secret = None
    user.totp_enabled_at = None
    user.totp_last_step = None
    user.recovery_codes = None
    await db.commit()


async def verify(db: AsyncSession, user: User, code: str) -> None:
    """Login step two: a current TOTP code or an unused recovery code.
    Raises MfaLockedError / WrongCodeError; commits the replay bookkeeping."""
    key = _lockout_key(user)
    if await lockout.is_locked(key):
        raise MfaLockedError
    if not enabled(user):
        raise NotEnrolledError
    step = totp.verify_code(_secret(user), code, last_step=user.totp_last_step)
    if step is not None:
        user.totp_last_step = step
    else:
        remaining = totp.consume_recovery_code(list(user.recovery_codes or []), code)
        if remaining is None:
            await lockout.record_failure(key)
            raise WrongCodeError
        user.recovery_codes = remaining
    await lockout.clear(key)
    await db.commit()


def recovery_codes_left(user: User) -> int:
    return len(user.recovery_codes or [])


async def sign_out_everywhere(db: AsyncSession, user: User) -> None:
    """Every session token issued so far fails the version check from now
    on; the caller re-issues its own cookie with the new version."""
    user.token_version += 1
    await db.commit()
