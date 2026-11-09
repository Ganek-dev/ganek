import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.security import hash_password, read_invite_token
from app.models import Company, CompanyMembership, User, UserInvite
from app.schemas.users import InviteCreate
from app.services.memberships import CompanySuspendedError

INVITE_TTL = timedelta(days=7)


class EmailTakenError(Exception):
    """A user with this email already exists."""


class AlreadyMemberError(Exception):
    """The account behind this email already holds a seat in the company."""


class AccountInactiveError(Exception):
    """The email belongs to a deactivated account, which cannot sign in to join."""


class InviteEmailMismatchError(Exception):
    """The signed-in account is not the one the invite was sent to."""


class InviteExistsError(Exception):
    """A pending, unexpired invite for this email already exists."""


class InviteExpiredError(Exception):
    """The invite's deadline has passed."""


class IdentityLinkedError(Exception):
    """The SSO identity already belongs to another account."""


def _now() -> datetime:
    return datetime.now(UTC)


async def _email_has_account(db: AsyncSession, email: str) -> bool:
    count = (
        await db.execute(select(func.count()).select_from(User).where(User.email == email))
    ).scalar_one()
    return bool(count)


async def account_for_email(db: AsyncSession, email: str) -> User | None:
    """The account behind ``email``, compared case-insensitively."""
    return (
        await db.execute(select(User).where(func.lower(User.email) == email.lower()))
    ).scalar_one_or_none()


async def _has_seat(db: AsyncSession, *, user_id: uuid.UUID, company_id: uuid.UUID) -> bool:
    count = (
        await db.execute(
            select(func.count())
            .select_from(CompanyMembership)
            .where(CompanyMembership.user_id == user_id, CompanyMembership.company_id == company_id)
        )
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
    """Create a pending invite; an expired leftover for the same email is replaced.

    Slice 7 of card "SSO + multi-company user membership": an email whose
    account belongs to another company can be invited too; that person
    signs in and joins (``join_invite``) instead of creating an account.
    """
    account = await account_for_email(db, payload.email)
    if account is not None:
        if await _has_seat(db, user_id=account.id, company_id=company.id):
            raise AlreadyMemberError
        if not account.is_active:
            raise AccountInactiveError
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


async def accept_invite_google(db: AsyncSession, invite: UserInvite, google_sub: str) -> User:
    """Create the invited user from a Google identity (no password) and consume the invite."""
    if invite.expires_at <= _now():
        raise InviteExpiredError
    if await _email_has_account(db, invite.email):
        raise EmailTakenError
    sub_taken = (
        await db.execute(
            select(func.count()).select_from(User).where(User.google_sub == google_sub)
        )
    ).scalar_one()
    if sub_taken:
        raise EmailTakenError
    user = User(
        company_id=invite.company_id,
        email=invite.email,
        password_hash=None,
        role=invite.role,
        google_sub=google_sub,
    )
    db.add(user)
    await db.delete(invite)
    await db.commit()
    await db.refresh(user)
    return user


async def accept_invite_oidc(
    db: AsyncSession, invite: UserInvite, *, oidc_issuer: str, oidc_sub: str
) -> User:
    """Create the invited user from the instance's OIDC identity (no
    password), keyed on (issuer, sub), and consume the invite."""
    if invite.expires_at <= _now():
        raise InviteExpiredError
    if await _email_has_account(db, invite.email):
        raise EmailTakenError
    sub_taken = (
        await db.execute(
            select(func.count())
            .select_from(User)
            .where(User.oidc_issuer == oidc_issuer, User.oidc_sub == oidc_sub)
        )
    ).scalar_one()
    if sub_taken:
        raise IdentityLinkedError
    user = User(
        company_id=invite.company_id,
        email=invite.email,
        password_hash=None,
        role=invite.role,
        oidc_issuer=oidc_issuer,
        oidc_sub=oidc_sub,
    )
    db.add(user)
    await db.delete(invite)
    await db.commit()
    await db.refresh(user)
    return user


async def join_invite(db: AsyncSession, invite: UserInvite, user: User) -> User:
    """Give the signed-in ``user`` the invited seat and make it their active
    company, consuming the invite. Only the account the invite was sent to
    may join with it; a person already holding a seat there is refused."""
    if invite.expires_at <= _now():
        raise InviteExpiredError
    if user.email.casefold() != invite.email.casefold():
        raise InviteEmailMismatchError
    if await _has_seat(db, user_id=user.id, company_id=invite.company_id):
        raise AlreadyMemberError
    if invite.company.suspended_at is not None:
        raise CompanySuspendedError(invite.company)
    # company and role move together: the membership listener inserts the
    # new seat from the user's active company and role
    user.company_id = invite.company_id
    user.role = invite.role
    await db.delete(invite)
    await db.commit()
    await db.refresh(user)
    return user


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
