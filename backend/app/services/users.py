import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_password
from app.models import Company, User, UserRole
from app.schemas.users import UserCreate, UserUpdate


class EmailTakenError(Exception):
    """A user with this email already exists."""


class LastAdminError(Exception):
    """Refuses to remove the company's last active admin."""


async def list_users(db: AsyncSession, company: Company) -> list[User]:
    return list(
        (
            await db.execute(
                select(User).where(User.company_id == company.id).order_by(User.created_at)
            )
        )
        .scalars()
        .all()
    )


async def get_user(db: AsyncSession, company: Company, user_id: uuid.UUID) -> User | None:
    return (
        await db.execute(select(User).where(User.company_id == company.id, User.id == user_id))
    ).scalar_one_or_none()


async def create_user(db: AsyncSession, company: Company, payload: UserCreate) -> User:
    taken = (
        await db.execute(select(func.count()).select_from(User).where(User.email == payload.email))
    ).scalar_one()
    if taken:
        raise EmailTakenError
    user = User(
        company_id=company.id,
        email=payload.email,
        password_hash=hash_password(payload.password),
        role=payload.role,
    )
    db.add(user)
    await db.commit()
    return user


async def _active_admin_count(db: AsyncSession, company: Company) -> int:
    return (
        await db.execute(
            select(func.count())
            .select_from(User)
            .where(
                User.company_id == company.id,
                User.role == UserRole.ADMIN,
                User.is_active.is_(True),
            )
        )
    ).scalar_one()


async def update_user(db: AsyncSession, company: Company, user: User, payload: UserUpdate) -> User:
    """Apply role/active changes, protecting the last active admin.

    Demoting or deactivating the only remaining admin is refused so a
    company can never lock itself out.
    """
    demoting_admin = user.role is UserRole.ADMIN and (
        (payload.role is not None and payload.role is not UserRole.ADMIN)
        or payload.is_active is False
    )
    if demoting_admin and await _active_admin_count(db, company) <= 1:
        raise LastAdminError
    if payload.role is not None:
        user.role = payload.role
    if payload.is_active is not None:
        user.is_active = payload.is_active
        if payload.is_active is False:
            # kill the deactivated user's live sessions immediately
            user.token_version += 1
    await db.commit()
    await db.refresh(user)
    return user
