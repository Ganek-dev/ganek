from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.security import hash_password, verify_password
from app.models import Company, User, UserRole
from app.services.slugs import slugify, with_random_suffix


class RegistrationClosedError(Exception):
    """Single-tenant instance already has its company."""


class EmailTakenError(Exception):
    """A user with this email already exists."""


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
    user = (await db.execute(select(User).where(User.email == email))).scalar_one_or_none()
    if user is None or not verify_password(password, user.password_hash):
        return None
    user.last_login_at = datetime.now(UTC)
    await db.commit()
    return user
