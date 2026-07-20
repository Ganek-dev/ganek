from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.tenancy import get_company_by_slug, get_current_company, get_single_company
from app.models import Company, User, UserRole
from tests.db import database_reachable

pytestmark = pytest.mark.skipif(
    not database_reachable(), reason="database not reachable (start postgres or use CI)"
)


async def _make_company(db: AsyncSession) -> Company:
    company = Company(slug=f"tenant-{uuid4().hex[:8]}", name="Tenant Co")
    db.add(company)
    await db.commit()
    return company


@pytest.mark.usefixtures("migrated_db")
async def test_get_company_by_slug(db_session: AsyncSession) -> None:
    company = await _make_company(db_session)
    found = await get_company_by_slug(company.slug, db_session)
    assert found.id == company.id


@pytest.mark.usefixtures("migrated_db")
async def test_get_company_by_slug_404(db_session: AsyncSession) -> None:
    with pytest.raises(HTTPException) as exc:
        await get_company_by_slug("no-such-company", db_session)
    assert exc.value.status_code == 404


@pytest.mark.usefixtures("migrated_db")
async def test_get_current_company_resolves_users_company(db_session: AsyncSession) -> None:
    company = await _make_company(db_session)
    user = User(
        company_id=company.id,
        email=f"member-{uuid4().hex[:8]}@vetd-ci.dev",
        password_hash="irrelevant",
        role=UserRole.MEMBER,
    )
    db_session.add(user)
    await db_session.commit()
    found = await get_current_company(user, db_session)
    assert found.id == company.id


@pytest.mark.usefixtures("migrated_db")
async def test_get_single_company_returns_oldest(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    await _make_company(db_session)
    monkeypatch.setattr(settings, "mode", "single")
    company = await get_single_company(db_session)
    assert isinstance(company, Company)


@pytest.mark.usefixtures("migrated_db")
async def test_get_single_company_404_in_multi_mode(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "mode", "multi")
    with pytest.raises(HTTPException) as exc:
        await get_single_company(db_session)
    assert exc.value.status_code == 404
