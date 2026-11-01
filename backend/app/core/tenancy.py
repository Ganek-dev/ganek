"""Tenancy resolution - the single place a request is bound to a company.

Hard rule: routers never hand-write ``WHERE company_id = ...``; they take a
``Company`` from one of these dependencies and pass it to services.
"""

from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.db import get_db
from app.core.security import SESSION_COOKIE_NAME, read_session_token
from app.models import ApiKey, Company, User, UserRole

DbSession = Annotated[AsyncSession, Depends(get_db)]

_UNAUTHENTICATED = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated"
)


async def get_current_user(request: Request, db: DbSession) -> User:
    token = request.cookies.get(SESSION_COOKIE_NAME)
    parsed = read_session_token(token) if token else None
    if parsed is None:
        raise _UNAUTHENTICATED
    user_id, token_version = parsed
    user = await db.get(User, user_id)
    if user is None or not user.is_active or user.token_version != token_version:
        # unknown, deactivated, or a session predating a password change /
        # forced logout - all rejected as unauthenticated
        raise _UNAUTHENTICATED
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


async def require_admin(user: CurrentUser) -> User:
    if user.role is not UserRole.ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This action requires an admin account",
        )
    return user


AdminUser = Annotated[User, Depends(require_admin)]


async def get_current_company(user: CurrentUser, db: DbSession) -> Company:
    """Admin context: the company of the authenticated user."""
    company = await db.get(Company, user.company_id)
    if company is None:
        # FK guarantees existence; treat a stale session as unauthenticated.
        raise _UNAUTHENTICATED
    return company


CurrentCompany = Annotated[Company, Depends(get_current_company)]


def _forbid_reviewer(user: User) -> None:
    if user.role is UserRole.REVIEWER:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This action requires a recruiter account",
        )


async def require_staff(user: CurrentUser) -> User:
    """Admin or member: the recruiter routes a reviewer never reaches (spec 4.1)."""
    _forbid_reviewer(user)
    return user


StaffUser = Annotated[User, Depends(require_staff)]


async def get_staff_company(user: StaffUser, db: DbSession) -> Company:
    return await get_current_company(user, db)


StaffCompany = Annotated[Company, Depends(get_staff_company)]


def _bearer(request: Request) -> str | None:
    header = request.headers.get("authorization", "")
    scheme, _, token = header.partition(" ")
    return token.strip() if scheme.lower() == "bearer" and token else None


async def _company_for_key(db: AsyncSession, token: str, *, write: bool) -> Company:
    _, company = await _key_and_company(db, token, write=write)
    return company


async def _key_and_company(db: AsyncSession, token: str, *, write: bool) -> tuple[ApiKey, Company]:
    from app.services import api_keys  # local: services import tenancy types

    try:
        return await api_keys.authenticate_key(db, token, write=write)
    except api_keys.KeyRejected:
        raise _UNAUTHENTICATED from None
    except api_keys.ScopeTooLow:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="This API key is read-only"
        ) from None


async def _staff_session_user(request: Request, db: DbSession) -> User:
    """The session branch of the routes a key may use: a key stays
    unrestricted, a reviewer session stays out."""
    user = await get_current_user(request, db)
    _forbid_reviewer(user)
    return user


async def _staff_session_company(request: Request, db: DbSession) -> Company:
    return await get_current_company(await _staff_session_user(request, db), db)


async def get_api_company(request: Request, db: DbSession) -> Company:
    """Read access for integrations (card D4): a bearer API key OR the
    session cookie. Routers use this only on read endpoints."""
    token = _bearer(request)
    if token is not None:
        return await _company_for_key(db, token, write=False)
    return await _staff_session_company(request, db)


ApiCompany = Annotated[Company, Depends(get_api_company)]


class ReadPrincipal:
    """Who is reading a candidate on a route a key may use: the company
    always, plus the user (session) or the key (bearer) for the access log."""

    def __init__(self, company: Company, user: User | None, api_key: ApiKey | None) -> None:
        self.company = company
        self.user = user
        self.api_key = api_key


async def get_read_principal(request: Request, db: DbSession) -> ReadPrincipal:
    token = _bearer(request)
    if token is not None:
        key, company = await _key_and_company(db, token, write=False)
        return ReadPrincipal(company, None, key)
    user = await _staff_session_user(request, db)
    return ReadPrincipal(await get_current_company(user, db), user, None)


ReadActor = Annotated[ReadPrincipal, Depends(get_read_principal)]


class WritePrincipal:
    """Who is acting on a write route a key may use: the company always,
    the user only for sessions (keys leave the activity actor empty)."""

    def __init__(self, company: Company, user: User | None) -> None:
        self.company = company
        self.user = user


async def get_write_principal(request: Request, db: DbSession) -> WritePrincipal:
    token = _bearer(request)
    if token is not None:
        return WritePrincipal(await _company_for_key(db, token, write=True), None)
    user = await _staff_session_user(request, db)
    return WritePrincipal(await get_current_company(user, db), user)


WriteActor = Annotated[WritePrincipal, Depends(get_write_principal)]


async def get_company_by_slug(slug: str, db: DbSession) -> Company:
    """Public context (multi mode): company from the URL slug."""
    company = (await db.execute(select(Company).where(Company.slug == slug))).scalar_one_or_none()
    if company is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Company not found")
    return company


PublicCompany = Annotated[Company, Depends(get_company_by_slug)]


async def get_single_company(db: DbSession) -> Company:
    """Public context (single mode): the instance's one company.

    404s when the instance is not set up yet, or when called on a
    multi-tenant instance (those routes resolve by slug instead).
    """
    if settings.mode != "single":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    company = (
        await db.execute(select(Company).order_by(Company.created_at).limit(1))
    ).scalar_one_or_none()
    if company is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Instance is not set up yet"
        )
    return company


SingleCompany = Annotated[Company, Depends(get_single_company)]
