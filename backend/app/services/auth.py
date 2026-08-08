from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import lockout
from app.core.config import settings
from app.core.security import hash_password, verify_password
from app.models import Company, User, UserRole
from app.services.slugs import slugify, with_random_suffix


class RegistrationClosedError(Exception):
    """Single-tenant instance already has its company."""


class EmailTakenError(Exception):
    """A user with this email already exists."""


class AccountLockedError(Exception):
    """Too many failed login attempts for this account."""


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

    company = Company(slug=await _unique_slug(db, slugify(company_name)), name=company_name)
    db.add(company)
    await db.flush()
    user = User(
        company_id=company.id,
        email=email,
        password_hash=hash_password(password),
        role=UserRole.ADMIN,
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
        or not user.is_active
        or user.password_hash is None
        or not verify_password(password, user.password_hash)
    ):
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
