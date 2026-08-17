from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import lockout
from app.core.config import settings
from app.core.security import hash_password, verify_password
from app.models import Company, User, UserRole
from app.services import email as email_service
from app.services.slugs import slugify, with_random_suffix


class RegistrationClosedError(Exception):
    """Single-tenant instance already has its company."""


class EmailTakenError(Exception):
    """A user with this email already exists."""


class AccountLockedError(Exception):
    """Too many failed login attempts for this account."""


class EmailUnverifiedError(Exception):
    """Correct credentials, but the signup email is not verified yet."""


def verification_required() -> bool:
    """Multi-mode signups verify their email BEFORE the company activates
    (M5.7 H4 — open signup on an exposed instance could mint companies and
    send branded email). Requires SMTP for two reasons: without it the
    verification link could never arrive, and the abuse this closes —
    sending branded email — needs SMTP anyway. Single mode closes after
    the first company and stays untouched."""
    return settings.mode == "multi" and email_service.smtp_configured()


async def _unique_slug(db: AsyncSession, base: str) -> str:
    slug = base
    while True:
        exists = (
            await db.execute(select(func.count()).select_from(Company).where(Company.slug == slug))
        ).scalar_one()
        if not exists:
            return slug
        slug = with_random_suffix(base)


async def register_company_admin(
    db: AsyncSession, *, company_name: str, email: str, password: str
) -> User:
    """Create a company with its first (admin) user.

    In single mode this is the one-time setup: once a company exists,
    registration is closed.
    """
    if settings.mode == "single":
        companies = (await db.execute(select(func.count()).select_from(Company))).scalar_one()
        if companies:
            raise RegistrationClosedError
    email_taken = (
        await db.execute(select(func.count()).select_from(User).where(User.email == email))
    ).scalar_one()
    if email_taken:
        raise EmailTakenError

    pending = verification_required()
    company = Company(
        slug=await _unique_slug(db, slugify(company_name)),
        name=company_name,
        settings={"pending_verification": True} if pending else {},
    )
    db.add(company)
    await db.flush()
    user = User(
        company_id=company.id,
        email=email,
        password_hash=hash_password(password),
        role=UserRole.ADMIN,
        is_active=not pending,
    )
    db.add(user)
    await db.commit()
    return user


async def authenticate(db: AsyncSession, *, email: str, password: str) -> User | None:
    """Return the user on success, None on bad credentials.

    Raises AccountLockedError when the account is temporarily locked from
    repeated failures. Deactivated accounts never authenticate.
    """
    if await lockout.is_locked(email):
        raise AccountLockedError
    user = (await db.execute(select(User).where(User.email == email))).scalar_one_or_none()
    if (
        user is None
        or user.password_hash is None
        or not verify_password(password, user.password_hash)
    ):
        await lockout.record_failure(email)
        return None
    if not user.is_active:
        if await is_pending_verification(db, user):
            # right password, unverified signup: send them to their inbox
            # instead of a bare "invalid credentials"
            raise EmailUnverifiedError
        await lockout.record_failure(email)
        return None
    await lockout.clear(email)
    user.last_login_at = datetime.now(UTC)
    await db.commit()
    return user


async def change_password(
    db: AsyncSession, user: User, *, current_password: str, new_password: str
) -> bool:
    """Rotate the password and invalidate all existing sessions.

    Bumping token_version makes every session token issued before now
    fail validation, so a compromised session cannot survive a password
    change.
    """
    if user.password_hash is None or not verify_password(current_password, user.password_hash):
        return False
    user.password_hash = hash_password(new_password)
    user.token_version += 1
    await db.commit()
    return True


async def is_pending_verification(db: AsyncSession, user: User) -> bool:
    company = (
        await db.execute(select(Company).where(Company.id == user.company_id))
    ).scalar_one_or_none()
    return bool(company is not None and (company.settings or {}).get("pending_verification"))


async def verify_email(db: AsyncSession, user: User) -> None:
    """Flip a pending signup live: activate the admin and clear the marker."""
    company = (await db.execute(select(Company).where(Company.id == user.company_id))).scalar_one()
    new_settings = dict(company.settings or {})
    new_settings.pop("pending_verification", None)
    company.settings = new_settings
    user.is_active = True
    await db.commit()


async def password_reset_target(db: AsyncSession, *, email: str) -> tuple[User, Company] | None:
    """Resolve who a reset email may go to; None (quietly) for everyone else.

    Google-only accounts are eligible on purpose: the reset link proves
    control of the same inbox Google vouched for, so completing it simply
    ADDS password sign-in (password_hash is nullable since 0013).
    """
    user = (await db.execute(select(User).where(User.email == email))).scalar_one_or_none()
    if user is None or not user.is_active:
        return None
    company = (await db.execute(select(Company).where(Company.id == user.company_id))).scalar_one()
    return user, company


async def set_password(db: AsyncSession, user: User, *, new_password: str) -> None:
    """Reset-flow companion to change_password: no current-password check —
    the signed reset token was the proof. Bumps token_version, which both
    kills existing sessions and single-uses every outstanding reset link
    (they carry the version they were issued against)."""
    user.password_hash = hash_password(new_password)
    user.token_version += 1
    await db.commit()


async def register_company_google(
    db: AsyncSession, *, company_name: str, email: str, google_sub: str
) -> User:
    """Company + first admin from a Google-verified identity (no password)."""
    if settings.mode == "single":
        companies = (await db.execute(select(func.count()).select_from(Company))).scalar_one()
        if companies:
            raise RegistrationClosedError
    taken = (
        await db.execute(
            select(func.count())
            .select_from(User)
            .where((User.email == email) | (User.google_sub == google_sub))
        )
    ).scalar_one()
    if taken:
        raise EmailTakenError

    company = Company(slug=await _unique_slug(db, slugify(company_name)), name=company_name)
    db.add(company)
    await db.flush()
    user = User(
        company_id=company.id,
        email=email,
        password_hash=None,
        role=UserRole.ADMIN,
        google_sub=google_sub,
        last_login_at=datetime.now(UTC),
    )
    db.add(user)
    await db.commit()
    return user
