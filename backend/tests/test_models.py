from pathlib import Path
from uuid import uuid4

import pytest
from alembic.config import Config as AlembicConfig
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from alembic import command
from app.core.config import settings
from app.models import BillingAccount, Company, CompanyPlan, User, UserRole
from tests.db import database_reachable

pytestmark = pytest.mark.skipif(
    not database_reachable(), reason="database not reachable (start postgres or use CI)"
)

BACKEND_DIR = Path(__file__).parents[1]


@pytest.mark.usefixtures("migrated_db")
async def test_company_and_user_roundtrip() -> None:
    engine = create_async_engine(settings.database_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    slug = f"acme-{uuid4().hex[:8]}"
    async with factory() as session:
        company = Company(slug=slug, name="Acme Inc")
        session.add(company)
        await session.flush()
        user = User(
            company_id=company.id,
            email=f"admin-{uuid4().hex[:6]}@acme.test",
            password_hash="not-a-real-hash",
            role=UserRole.ADMIN,
        )
        session.add(user)
        await session.commit()

        assert company.created_at is not None
        assert company.theme == {}
        loaded = (
            await session.execute(select(User).where(User.company_id == company.id))
        ).scalar_one()
        assert loaded.role is UserRole.ADMIN
        assert loaded.last_login_at is None
    await engine.dispose()


@pytest.mark.usefixtures("migrated_db")
async def test_company_slug_is_unique() -> None:
    engine = create_async_engine(settings.database_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    slug = f"dup-{uuid4().hex[:8]}"
    async with factory() as session:
        session.add(Company(slug=slug, name="First"))
        await session.commit()
    async with factory() as session:
        session.add(Company(slug=slug, name="Second"))
        with pytest.raises(IntegrityError):
            await session.commit()
    await engine.dispose()


@pytest.mark.usefixtures("migrated_db")
def test_migration_is_idempotent_on_stamped_db() -> None:
    # upgrade head on an already-migrated DB is a no-op, not an error.
    # Sync test: alembic's env.py drives its own event loop via asyncio.run.
    cfg = AlembicConfig(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    command.upgrade(cfg, "head")


@pytest.mark.usefixtures("migrated_db")
async def test_user_google_sub_and_nullable_password(db_session: AsyncSession) -> None:
    company = Company(slug=f"g-{uuid4().hex[:8]}", name="Google Co")
    db_session.add(company)
    await db_session.flush()
    user = User(
        company_id=company.id,
        email=f"g-{uuid4().hex[:8]}@gmail.com",
        password_hash=None,
        role=UserRole.ADMIN,
        google_sub=f"sub-{uuid4().hex}",
    )
    db_session.add(user)
    await db_session.commit()
    assert user.has_password is False
    await db_session.delete(user)
    await db_session.delete(company)
    await db_session.commit()


@pytest.mark.usefixtures("migrated_db")
async def test_company_plan_defaults_to_self_hosted_and_billing_row_cascades() -> None:
    engine = create_async_engine(settings.database_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        company = Company(slug=f"plan-{uuid4().hex[:8]}", name="Plan Inc")
        session.add(company)
        await session.commit()
        await session.refresh(company)
        assert company.plan is CompanyPlan.SELF_HOSTED

        account = BillingAccount(company_id=company.id, stripe_customer_id=f"cus_{uuid4().hex}")
        session.add(account)
        await session.commit()

    # card B1d: the billing row loads with the company (the sync hosted
    # policy reads the trial end off it, never lazy-loading)
    async with factory() as session:
        loaded = await session.get(Company, company.id)
        assert loaded is not None
        assert loaded.billing_account is not None
        assert loaded.billing_account.id == account.id
        listed = await session.scalar(select(Company).where(Company.id == company.id))
        assert listed is loaded

    async with factory() as session:
        company = await session.get(Company, company.id)
        assert company is not None
        await session.delete(company)
        await session.commit()
        left = await session.scalar(select(BillingAccount).where(BillingAccount.id == account.id))
        assert left is None
    await engine.dispose()
