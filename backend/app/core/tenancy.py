"""Tenancy resolution — the single place a request is bound to a company.

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
from app.models import Company, User

DbSession = Annotated[AsyncSession, Depends(get_db)]

_UNAUTHENTICATED = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated"
)


async def get_current_user(request: Request, db: DbSession) -> User:
    token = request.cookies.get(SESSION_COOKIE_NAME)
    user_id = read_session_token(token) if token else None
    if user_id is None:
        raise _UNAUTHENTICATED
    user = await db.get(User, user_id)
    if user is None:
        raise _UNAUTHENTICATED
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


async def get_current_company(user: CurrentUser, db: DbSession) -> Company:
    """Admin context: the company of the authenticated user."""
    company = await db.get(Company, user.company_id)
    if company is None:
        # FK guarantees existence; treat a stale session as unauthenticated.
        raise _UNAUTHENTICATED
    return company


CurrentCompany = Annotated[Company, Depends(get_current_company)]


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
