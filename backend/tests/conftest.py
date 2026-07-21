from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from alembic.config import Config as AlembicConfig
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from alembic import command
from app.core.config import settings
from app.core.db import get_db
from app.main import app

BACKEND_DIR = Path(__file__).parents[1]


@pytest.fixture(scope="session")
def bucket() -> None:
    import time

    from app.services import storage

    last: Exception | None = None
    for _ in range(20):
        try:
            storage.ensure_bucket()
            return
        except Exception as exc:  # noqa: BLE001 - minio may still be starting
            last = exc
            time.sleep(0.5)
    raise RuntimeError(f"minio never became ready: {last}")


@pytest.fixture(scope="session")
def migrated_db() -> None:
    cfg = AlembicConfig(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    command.upgrade(cfg, "head")


@pytest.fixture
async def db_session() -> AsyncIterator[AsyncSession]:
    """Direct database session for service/dependency-level tests."""
    engine = create_async_engine(settings.database_url, poolclass=NullPool)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    """HTTP client against the app with a per-test database engine.

    NullPool + a fresh engine per test avoids asyncpg connections leaking
    across pytest-asyncio event loops. The engine connects lazily, so
    DB-free tests (e.g. health) never touch postgres.
    """
    engine = create_async_engine(settings.database_url, poolclass=NullPool)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async def _get_db() -> AsyncIterator[AsyncSession]:
        async with factory() as session:
            yield session

    app.dependency_overrides[get_db] = _get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()
    await engine.dispose()
