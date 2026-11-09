"""company_memberships (card "SSO + multi-company user membership", slice 1):
every user has exactly one membership mirroring users.company_id and
users.role, from the 0056 backfill and from the ORM listeners after it."""

import asyncio
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from alembic.config import Config as AlembicConfig
from httpx import AsyncClient
from sqlalchemy import delete, insert, select, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from alembic import command
from app.core.config import settings
from tests.db import database_reachable

pytestmark = pytest.mark.skipif(
    not database_reachable(),
    reason="database required (start postgres or use CI)",
)

PASSWORD = "a-long-secure-password"
BACKEND_DIR = Path(__file__).parents[1]


@pytest.fixture
def multi_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "mode", "multi")


async def _memberships(db: AsyncSession, user_id: UUID) -> list[tuple[UUID, str]]:
    from app.models import CompanyMembership

    rows = await db.execute(
        select(CompanyMembership.company_id, CompanyMembership.role).where(
            CompanyMembership.user_id == user_id
        )
    )
    return [(company_id, role.value) for company_id, role in rows.all()]


async def _register(client: AsyncClient) -> dict[str, str]:
    admin = {"email": f"admin-{uuid4().hex[:8]}@ganek-ci.dev", "password": PASSWORD}
    resp = await client.post(
        "/api/v1/auth/register",
        json={"company_name": f"Member Co {uuid4().hex[:6]}", **admin},
    )
    assert resp.status_code == 201, resp.text
    return admin


@pytest.mark.usefixtures("migrated_db", "multi_mode")
async def test_new_users_get_one_membership_that_follows_role_changes(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    from app.models import User

    admin = await _register(client)
    admin_row = (
        await db_session.execute(select(User).where(User.email == admin["email"]))
    ).scalar_one()
    company_id = admin_row.company_id
    assert await _memberships(db_session, admin_row.id) == [(company_id, "admin")]

    resp = await client.post(
        "/api/v1/users",
        json={"email": f"m-{uuid4().hex[:8]}@ganek-ci.dev", "password": PASSWORD, "role": "member"},
    )
    assert resp.status_code == 201, resp.text
    member_id = UUID(resp.json()["id"])
    assert await _memberships(db_session, member_id) == [(company_id, "member")]

    resp = await client.patch(f"/api/v1/users/{member_id}", json={"role": "reviewer"})
    assert resp.status_code == 200, resp.text
    db_session.expire_all()
    assert await _memberships(db_session, member_id) == [(company_id, "reviewer")]

    # a change that leaves the role alone keeps the one row as it is
    resp = await client.patch(f"/api/v1/users/{member_id}", json={"is_active": False})
    assert resp.status_code == 200, resp.text
    db_session.expire_all()
    assert await _memberships(db_session, member_id) == [(company_id, "reviewer")]


@pytest.mark.usefixtures("migrated_db", "multi_mode")
async def test_anonymized_users_keep_their_membership(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _register(client)
    resp = await client.post(
        "/api/v1/users",
        json={"email": f"m-{uuid4().hex[:8]}@ganek-ci.dev", "password": PASSWORD, "role": "member"},
    )
    member_id = UUID(resp.json()["id"])
    assert (await client.post(f"/api/v1/users/{member_id}/anonymize")).status_code == 204
    db_session.expire_all()
    assert [role for _, role in await _memberships(db_session, member_id)] == ["member"]


@pytest.mark.usefixtures("migrated_db")
async def test_memberships_go_with_the_company(db_session: AsyncSession) -> None:
    from app.models import Company, CompanyMembership, User, UserRole

    company = Company(slug=f"gone-{uuid4().hex[:8]}", name="Gone Co")
    db_session.add(company)
    await db_session.flush()
    user = User(
        company_id=company.id,
        email=f"gone-{uuid4().hex[:8]}@ganek-ci.dev",
        role=UserRole.ADMIN,
    )
    db_session.add(user)
    await db_session.commit()
    assert await _memberships(db_session, user.id) == [(company.id, "admin")]

    # the operator tenant delete removes the company row; the FK cascade
    # takes the users and their memberships with it
    await db_session.execute(delete(Company).where(Company.id == company.id))
    await db_session.commit()
    left = await db_session.scalar(
        select(CompanyMembership.id).where(CompanyMembership.company_id == company.id)
    )
    assert left is None


def _alembic() -> AlembicConfig:
    cfg = AlembicConfig(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    return cfg


@pytest.mark.usefixtures("migrated_db")
def test_0056_backfills_one_membership_per_existing_user() -> None:
    """The migration moves every existing user, any role and any active
    state, to exactly one membership with the same company and role."""
    cfg = _alembic()
    command.downgrade(cfg, "0055")
    try:
        company_id = uuid4()
        users = {uuid4(): "admin", uuid4(): "member", uuid4(): "reviewer"}

        async def _seed() -> None:
            from app.models import Company, User, UserRole

            # Core inserts on the tables: column defaults apply, the ORM
            # membership listener does not (its table is gone at 0055)
            engine = create_async_engine(settings.database_url, poolclass=NullPool)
            async with engine.begin() as conn:
                await conn.execute(
                    insert(Company.__table__).values(
                        id=company_id, slug=f"pre-{company_id.hex[:8]}", name="Pre Co"
                    )
                )
                for user_id, role in users.items():
                    await conn.execute(
                        insert(User.__table__).values(
                            id=user_id,
                            company_id=company_id,
                            email=f"pre-{user_id.hex[:8]}@ganek-ci.dev",
                            role=UserRole(role),
                            is_active=role != "reviewer",
                        )
                    )
            await engine.dispose()

        asyncio.run(_seed())
    finally:
        command.upgrade(cfg, "head")

    async def _check() -> tuple[list[tuple[UUID, UUID, str]], int, int]:
        engine = create_async_engine(settings.database_url, poolclass=NullPool)
        async with engine.connect() as conn:
            rows = (
                await conn.execute(
                    text(
                        "SELECT user_id, company_id, role FROM company_memberships"
                        " WHERE company_id = :c"
                    ),
                    {"c": company_id},
                )
            ).all()
            total_users = (await conn.execute(text("SELECT count(*) FROM users"))).scalar_one()
            mirrored = (
                await conn.execute(
                    text(
                        "SELECT count(*) FROM users u JOIN company_memberships m"
                        " ON m.user_id = u.id AND m.company_id = u.company_id AND m.role = u.role"
                    )
                )
            ).scalar_one()
        await engine.dispose()
        return [(r[0], r[1], r[2]) for r in rows], total_users, mirrored

    rows, total_users, mirrored = asyncio.run(_check())
    assert sorted(rows) == sorted((u, company_id, r) for u, r in users.items())
    # every user in the database, not only the ones seeded here
    assert mirrored == total_users
