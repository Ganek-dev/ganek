"""Team list, role edits and the last-admin check over memberships (card
"SSO + multi-company user membership", slice 4): a company's team is every
seat in it, whichever company is active for the person, the role shown and
edited is that company's seat, and account-wide changes are refused for a
person another company still has."""

from typing import Any
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from tests.db import database_reachable

pytestmark = pytest.mark.skipif(
    not database_reachable(),
    reason="database required (start postgres or use CI)",
)

PASSWORD = "a-long-secure-password"


@pytest.fixture
def multi_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "mode", "multi")


async def _register(client: AsyncClient, label: str) -> dict[str, Any]:
    """A fresh company with its admin signed in on ``client``."""
    admin = {"email": f"{label}-{uuid4().hex[:8]}@ganek-ci.dev", "password": PASSWORD}
    resp = await client.post(
        "/api/v1/auth/register",
        json={"company_name": f"{label} Co {uuid4().hex[:6]}", **admin},
    )
    assert resp.status_code == 201, resp.text
    me = resp.json()
    return {**admin, "id": me["id"], "company_id": me["company_id"]}


async def _login(client: AsyncClient, email: str) -> None:
    client.cookies.clear()
    resp = await client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
    assert resp.status_code == 200, resp.text


async def _add_seat(db: AsyncSession, user_id: str, company_id: str, role: str) -> None:
    from app.models import CompanyMembership, UserRole

    db.add(
        CompanyMembership(user_id=UUID(user_id), company_id=UUID(company_id), role=UserRole(role))
    )
    await db.commit()


async def _seat_role(db: AsyncSession, user_id: str, company_id: str) -> str:
    from app.models import CompanyMembership

    role = (
        await db.execute(
            select(CompanyMembership.role).where(
                CompanyMembership.user_id == UUID(user_id),
                CompanyMembership.company_id == UUID(company_id),
            )
        )
    ).scalar_one()
    return str(getattr(role, "value", role))


async def _team(client: AsyncClient) -> dict[str, dict[str, Any]]:
    resp = await client.get("/api/v1/users")
    assert resp.status_code == 200, resp.text
    return {u["id"]: u for u in resp.json()}


async def _two_companies_one_shared(
    client: AsyncClient, db: AsyncSession, role_in_b: str = "member"
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Company A (its admin is active there) and company B, where A's admin
    also holds a ``role_in_b`` seat. Ends signed in as B's admin."""
    a = await _register(client, "alpha")
    b = await _register(client, "beta")
    await _add_seat(db, a["id"], b["company_id"], role_in_b)
    await _login(client, b["email"])
    return a, b


@pytest.mark.usefixtures("migrated_db", "multi_mode")
async def test_team_lists_a_seat_whose_active_company_is_elsewhere(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    a, b = await _two_companies_one_shared(client, db_session, "reviewer")
    team = await _team(client)
    assert set(team) == {a["id"], b["id"]}
    # the role shown is the seat in B, not the admin role of A's active seat
    assert team[a["id"]]["role"] == "reviewer"
    assert team[b["id"]]["role"] == "admin"

    # and A's team does not list B's admin
    await _login(client, a["email"])
    assert set(await _team(client)) == {a["id"]}


@pytest.mark.usefixtures("migrated_db", "multi_mode")
async def test_role_edit_moves_only_this_companys_seat(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    a, b = await _two_companies_one_shared(client, db_session, "member")
    resp = await client.patch(f"/api/v1/users/{a['id']}", json={"role": "reviewer"})
    assert resp.status_code == 200, resp.text
    assert resp.json()["role"] == "reviewer"
    assert await _seat_role(db_session, a["id"], b["company_id"]) == "reviewer"
    # the seat in A (the active one) keeps its admin role
    assert await _seat_role(db_session, a["id"], a["company_id"]) == "admin"
    await _login(client, a["email"])
    me = (await client.get("/api/v1/auth/me")).json()
    assert me["role"] == "admin"
    assert me["company_id"] == a["company_id"]

    # switching into B now carries the edited role
    resp = await client.post("/api/v1/auth/switch-company", json={"company_id": b["company_id"]})
    assert resp.status_code == 200, resp.text
    assert resp.json()["role"] == "reviewer"


@pytest.mark.usefixtures("migrated_db", "multi_mode")
async def test_role_edit_of_the_active_seat_still_moves_the_session_role(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    a, b = await _two_companies_one_shared(client, db_session, "member")
    resp = await client.post(
        "/api/v1/users",
        json={"email": f"m-{uuid4().hex[:8]}@ganek-ci.dev", "password": PASSWORD, "role": "member"},
    )
    assert resp.status_code == 201, resp.text
    member_id = resp.json()["id"]
    resp = await client.patch(f"/api/v1/users/{member_id}", json={"role": "admin"})
    assert resp.status_code == 200, resp.text
    assert resp.json()["role"] == "admin"
    assert await _seat_role(db_session, member_id, b["company_id"]) == "admin"


@pytest.mark.usefixtures("migrated_db", "multi_mode")
async def test_an_admin_seat_held_from_elsewhere_counts_for_the_last_admin_check(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    a, b = await _two_companies_one_shared(client, db_session, "admin")
    # B has two admin seats (B's own admin and A's admin), so B's admin may step down
    resp = await client.patch(f"/api/v1/users/{b['id']}", json={"role": "member"})
    assert resp.status_code == 200, resp.text
    # now A's admin is B's only admin seat: demoting it is refused, even
    # by that admin acting in B
    await _login(client, a["email"])
    resp = await client.post("/api/v1/auth/switch-company", json={"company_id": b["company_id"]})
    assert resp.status_code == 200, resp.text
    resp = await client.patch(f"/api/v1/users/{a['id']}", json={"role": "member"})
    assert resp.status_code == 409, resp.text
    assert "last active admin" in resp.json()["detail"]
    assert await _seat_role(db_session, a["id"], b["company_id"]) == "admin"


@pytest.mark.usefixtures("migrated_db", "multi_mode")
async def test_an_admin_role_in_another_company_does_not_count_here(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    # A's admin is only a member in B, so B's own admin is still B's last admin
    _a, b = await _two_companies_one_shared(client, db_session, "member")
    resp = await client.patch(f"/api/v1/users/{b['id']}", json={"role": "member"})
    assert resp.status_code == 409, resp.text


@pytest.mark.usefixtures("migrated_db", "multi_mode")
async def test_account_wide_changes_are_refused_for_a_shared_person(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    from app.models import User

    a, _b = await _two_companies_one_shared(client, db_session, "member")
    resp = await client.patch(f"/api/v1/users/{a['id']}", json={"is_active": False})
    assert resp.status_code == 409, resp.text
    assert "another company" in resp.json()["detail"]
    resp = await client.post(f"/api/v1/users/{a['id']}/anonymize")
    assert resp.status_code == 409, resp.text
    assert "another company" in resp.json()["detail"]

    row = (await db_session.execute(select(User).where(User.id == UUID(a["id"])))).scalar_one()
    await db_session.refresh(row)
    assert row.is_active is True
    assert row.email == a["email"]
    # a no-op active flag is not an account-wide change
    resp = await client.patch(f"/api/v1/users/{a['id']}", json={"is_active": True})
    assert resp.status_code == 200, resp.text
    # and A's admin can still sign in to A
    await _login(client, a["email"])


@pytest.mark.usefixtures("migrated_db", "multi_mode")
async def test_a_user_without_a_seat_here_is_not_found(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    a = await _register(client, "alpha")
    b = await _register(client, "beta")
    # B's admin cannot see or edit A's admin, who has no seat in B
    resp = await client.patch(f"/api/v1/users/{a['id']}", json={"role": "member"})
    assert resp.status_code == 404, resp.text
    resp = await client.post(f"/api/v1/users/{a['id']}/anonymize")
    assert resp.status_code == 404, resp.text
    assert set(await _team(client)) == {b["id"]}
