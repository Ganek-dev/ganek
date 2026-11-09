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
from app.core.security import (
    IMPERSONATION_COOKIE_NAME,
    SESSION_COOKIE_NAME,
    ImpersonationClaim,
    read_impersonation_token,
    read_session_token,
)
from app.models import ApiKey, Company, User, UserRole

DbSession = Annotated[AsyncSession, Depends(get_db)]

_UNAUTHENTICATED = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated"
)

# what a candidate sees on a suspended tenant's careers page: nothing about why
PUBLIC_UNAVAILABLE_DETAIL = "This careers page is temporarily unavailable"


def suspended_detail(company: Company) -> str:
    reason = (company.suspension_reason or "").strip()
    return (
        "This workspace is suspended"
        + (f": {reason}" if reason else "")
        + ". Contact the instance operator to restore access."
    )


def reject_suspended(company: Company | None) -> None:
    """Sign-in, sessions and API keys of a suspended tenant (operator plane)
    answer 403 with the operator's reason, so the admin login can show it."""
    if company is not None and company.suspended_at is not None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=suspended_detail(company))


def _reject_suspended_public(company: Company) -> None:
    if company.suspended_at is not None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=PUBLIC_UNAVAILABLE_DETAIL
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
    impersonated = await _impersonated_user(request, db, user)
    if impersonated is not None:
        user = impersonated
    from app.services import memberships  # local: services import tenancy types

    # the active company counts only while a membership row backs it: a
    # seat that was taken away ends every session bound to that company
    company = await memberships.active_company(db, user)
    if company is None:
        raise _UNAUTHENTICATED
    reject_suspended(company)
    return user


# what an impersonating operator may send: reads only, so nothing the
# tenant sees afterwards was done in a tenant user's name
_READ_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
IMPERSONATION_READ_ONLY_DETAIL = (
    "Read-only while impersonating. End the impersonation to make changes."
)


def impersonation_of(request: Request) -> ImpersonationClaim | None:
    """The impersonation get_current_user honoured on this request, if any."""
    claim = getattr(request.state, "impersonation", None)
    return claim if isinstance(claim, ImpersonationClaim) else None


async def _impersonated_user(request: Request, db: AsyncSession, session_user: User) -> User | None:
    """Operator plane: a superadmin's session plus a valid impersonation
    cookie reads as the tenant user named in it, for one hour and for reads
    only. A cookie that is expired, forged, minted for another operator or
    for an older token version is ignored, so the operator is simply back
    in their own account."""
    token = request.cookies.get(IMPERSONATION_COOKIE_NAME)
    claim = read_impersonation_token(token) if token else None
    if claim is None:
        return None
    from app.core.ops import superadmin_ids  # local: core.ops imports this module

    if (
        claim.operator_id != session_user.id
        or claim.operator_version != session_user.token_version
        or session_user.id not in superadmin_ids()
    ):
        return None
    target = await db.get(User, claim.user_id)
    if target is None or not target.is_active or target.token_version != claim.user_version:
        return None
    if request.method not in _READ_METHODS:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail=IMPERSONATION_READ_ONLY_DETAIL
        )
    request.state.impersonation = claim
    return target


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
    """Admin context: the active company of the authenticated user (one of
    their memberships, checked in get_current_user)."""
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
        key, company = await api_keys.authenticate_key(db, token, write=write)
    except api_keys.KeyRejected:
        raise _UNAUTHENTICATED from None
    except api_keys.ScopeTooLow:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="This API key is read-only"
        ) from None
    reject_suspended(company)
    return key, company


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
    _reject_suspended_public(company)
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
    _reject_suspended_public(company)
    return company


SingleCompany = Annotated[Company, Depends(get_single_company)]
