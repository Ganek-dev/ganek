from pathlib import Path
from uuid import uuid4

import pytest
from alembic.config import Config as AlembicConfig
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from alembic import command
from app.core.config import settings
from app.models import Company, User, UserRole
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
async def test_migration_is_idempotent_on_stamped_db() -> None:
    # upgrade head on an already-migrated DB is a no-op, not an error
    cfg = AlembicConfig(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    command.upgrade(cfg, "head")
    engine = create_async_engine(settings.database_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        count = (await session.execute(select(func.count()).select_from(Company))).scalar_one()
        assert count >= 0
    await engine.dispose()
