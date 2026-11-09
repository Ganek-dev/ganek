"""Company memberships (card "SSO + multi-company user membership").

Slice 2: the active company of a user is ``users.company_id`` and the role
they act with is ``users.role``; both always equal one of their membership
rows. Tenancy (``core.tenancy.get_current_user``) refuses a session whose
active company has no membership row, and ``switch_company`` moves the
active company to another company the user holds a seat in, taking that
seat's role with it.
"""

import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Company, CompanyMembership, User, UserRole


class NotAMemberError(Exception):
    """The user holds no seat in that company (or it does not exist)."""


class CompanySuspendedError(Exception):
    """The target company is suspended by the instance operator."""

    def __init__(self, company: Company) -> None:
        super().__init__(company.id)
        self.company = company


@dataclass(frozen=True)
class Seat:
    company: Company
    role: UserRole
    active: bool


async def active_company(db: AsyncSession, user: User) -> Company | None:
    """The user's active company, only when a membership row backs it."""
    return (
        await db.execute(
            select(Company)
            .join(CompanyMembership, CompanyMembership.company_id == Company.id)
            .where(CompanyMembership.user_id == user.id, Company.id == user.company_id)
        )
    ).scalar_one_or_none()


async def list_seats(db: AsyncSession, user: User) -> list[Seat]:
    """Every company the user belongs to, the active one first, then by name."""
    rows = (
        await db.execute(
            select(Company, CompanyMembership.role)
            .join(CompanyMembership, CompanyMembership.company_id == Company.id)
            .where(CompanyMembership.user_id == user.id)
        )
    ).all()
    seats = [Seat(company=c, role=UserRole(r), active=c.id == user.company_id) for c, r in rows]
    return sorted(seats, key=lambda s: (not s.active, s.company.name.lower(), str(s.company.id)))


async def switch_company(db: AsyncSession, user: User, company_id: uuid.UUID) -> User:
    """Make ``company_id`` the user's active company with that seat's role.

    No seat (or no such company) is one error, so the answer never tells a
    user whether a company they do not belong to exists.
    """
    row = (
        await db.execute(
            select(Company, CompanyMembership.role)
            .join(CompanyMembership, CompanyMembership.company_id == Company.id)
            .where(CompanyMembership.user_id == user.id, Company.id == company_id)
        )
    ).one_or_none()
    if row is None:
        raise NotAMemberError(company_id)
    company, role = row
    if company.suspended_at is not None:
        raise CompanySuspendedError(company)
    if user.company_id != company.id or user.role != role:
        # role and company move together, so the membership listener's
        # upsert writes back the role the seat already has
        user.company_id = company.id
        user.role = UserRole(role)
        await db.commit()
        await db.refresh(user)
    return user
