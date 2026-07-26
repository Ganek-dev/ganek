import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.security import hash_password, read_invite_token
from app.models import Company, User, UserInvite
from app.schemas.users import InviteCreate

INVITE_TTL = timedelta(days=7)


class EmailTakenError(Exception):
    """A user with this email already exists."""


class InviteExistsError(Exception):
    """A pending, unexpired invite for this email already exists."""


class InviteExpiredError(Exception):
    """The invite's deadline has passed."""


def _now() -> datetime:
    return datetime.now(UTC)


async def _email_has_account(db: AsyncSession, email: str) -> bool:
    count = (
        await db.execute(select(func.count()).select_from(User).where(User.email == email))
    ).scalar_one()
    return bool(count)


async def list_invites(db: AsyncSession, company: Company) -> list[UserInvite]:
    return list(
        (
            await db.execute(
                select(UserInvite)
                .where(UserInvite.company_id == company.id)
                .order_by(UserInvite.created_at)
            )
        )
        .scalars()
        .all()
    )


async def get_invite(db: AsyncSession, company: Company, invite_id: uuid.UUID) -> UserInvite | None:
    return (
        await db.execute(
            select(UserInvite).where(
                UserInvite.company_id == company.id, UserInvite.id == invite_id
            )
        )
    ).scalar_one_or_none()


async def create_invite(db: AsyncSession, company: Company, payload: InviteCreate) -> UserInvite:
    """Create a pending invite; an expired leftover for the same email is replaced."""
    if await _email_has_account(db, payload.email):
        raise EmailTakenError
    existing = (
        await db.execute(
            select(UserInvite).where(
                UserInvite.company_id == company.id, UserInvite.email == payload.email
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        if existing.expires_at > _now():
            raise InviteExistsError
        await db.delete(existing)
        await db.flush()
    invite = UserInvite(
        company_id=company.id,
        email=payload.email,
        role=payload.role,
        expires_at=_now() + INVITE_TTL,
    )
    db.add(invite)
    await db.commit()
    await db.refresh(invite)
    return invite


async def resend_invite(db: AsyncSession, invite: UserInvite) -> UserInvite:
    """Push the deadline forward; the original emailed token stays usable too."""
    invite.expires_at = _now() + INVITE_TTL
    await db.commit()
    await db.refresh(invite)
    return invite


async def revoke_invite(db: AsyncSession, invite: UserInvite) -> None:
    await db.delete(invite)
    await db.commit()


async def invite_by_token(db: AsyncSession, token: str) -> UserInvite | None:
    invite_id = read_invite_token(token)
    if invite_id is None:
        return None
    return (
        await db.execute(
            select(UserInvite)
            .options(selectinload(UserInvite.company))
            .where(UserInvite.id == invite_id)
        )
    ).scalar_one_or_none()


async def accept_invite(db: AsyncSession, invite: UserInvite, password: str) -> User:
    """Create the invited user and consume the invite row."""
    if invite.expires_at <= _now():
        raise InviteExpiredError
    if await _email_has_account(db, invite.email):
        raise EmailTakenError
    user = User(
        company_id=invite.company_id,
        email=invite.email,
        password_hash=hash_password(password),
        role=invite.role,
    )
    db.add(user)
    await db.delete(invite)
    await db.commit()
    await db.refresh(user)
    return user
