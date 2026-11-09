"""Joining a second company by invite (card "SSO + multi-company user
membership", slice 7): an email whose account belongs to another company
can be invited; that person signs in and joins with the invite instead of
creating a second account. Their other seats stay untouched."""

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.security import create_invite_token
from app.models import User, UserInvite
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
    client.cookies.clear()
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


async def _invite(client: AsyncClient, email: str, role: str = "member") -> str:
    resp = await client.post("/api/v1/users/invites", json={"email": email, "role": role})
    assert resp.status_code == 201, resp.text
    return create_invite_token(UUID(resp.json()["id"]))


@pytest.mark.usefixtures("migrated_db", "multi_mode")
async def test_existing_account_signs_in_and_joins_a_second_company(
    client: AsyncClient,
) -> None:
    bob = await _register(client, "bob")
    alice = await _register(client, "alice")
    token = await _invite(client, bob["email"], role="member")

    # the accept page learns the email already has an account
    info = await client.get(f"/api/v1/public/invites/{token}")
    assert info.status_code == 200, info.text
    assert info.json()["existing_account"] is True

    # setting a password for a second account is still refused
    client.cookies.clear()
    resp = await client.post(
        f"/api/v1/public/invites/{token}/accept", json={"password": "another-password-1"}
    )
    assert resp.status_code == 409
    assert "Sign in" in resp.json()["detail"]

    # signed in, bob joins: alice's company becomes active with the invited role
    await _login(client, bob["email"])
    resp = await client.post("/api/v1/auth/join-invite", json={"token": token})
    assert resp.status_code == 200, resp.text
    assert resp.json()["company_id"] == alice["company_id"]
    assert resp.json()["role"] == "member"

    seats = (await client.get("/api/v1/auth/companies")).json()
    assert {(s["company_id"], s["role"], s["active"]) for s in seats} == {
        (alice["company_id"], "member", True),
        (bob["company_id"], "admin", False),
    }

    # the invite is consumed
    assert (await client.get(f"/api/v1/public/invites/{token}")).status_code == 404
    again = await client.post("/api/v1/auth/join-invite", json={"token": token})
    assert again.status_code == 404

    # his own company is one switch away, still as admin
    resp = await client.post("/api/v1/auth/switch-company", json={"company_id": bob["company_id"]})
    assert resp.status_code == 200, resp.text
    assert resp.json()["role"] == "admin"

    # alice's team lists him as shared with another company, invites are empty
    await _login(client, alice["email"])
    team = {u["email"]: u for u in (await client.get("/api/v1/users")).json()}
    assert team[bob["email"]]["in_other_companies"] is True
    assert (await client.get("/api/v1/users/invites")).json() == []


@pytest.mark.usefixtures("migrated_db", "multi_mode")
async def test_join_refusals_change_nothing(client: AsyncClient, db_session: AsyncSession) -> None:
    bob = await _register(client, "bob")
    carol = await _register(client, "carol")
    alice = await _register(client, "alice")

    # someone already on the team cannot be invited again
    resp = await client.post(
        "/api/v1/users/invites", json={"email": alice["email"], "role": "member"}
    )
    assert resp.status_code == 409
    assert resp.json()["detail"] == "This person is already on your team"

    token = await _invite(client, bob["email"])

    # not signed in
    client.cookies.clear()
    assert (await client.post("/api/v1/auth/join-invite", json={"token": token})).status_code == 401

    # signed in as someone else: the invite is not theirs to use
    await _login(client, carol["email"])
    resp = await client.post("/api/v1/auth/join-invite", json={"token": token})
    assert resp.status_code == 403
    seats = (await client.get("/api/v1/auth/companies")).json()
    assert [s["company_id"] for s in seats] == [carol["company_id"]]

    # garbage token
    assert (
        await client.post("/api/v1/auth/join-invite", json={"token": "nope"})
    ).status_code == 404

    # expired
    row = (
        await db_session.execute(select(UserInvite).where(UserInvite.email == bob["email"]))
    ).scalar_one()
    row.expires_at = datetime.now(UTC) - timedelta(days=1)
    await db_session.commit()
    await _login(client, bob["email"])
    assert (await client.post("/api/v1/auth/join-invite", json={"token": token})).status_code == 410
    seats = (await client.get("/api/v1/auth/companies")).json()
    assert [s["company_id"] for s in seats] == [bob["company_id"]]


@pytest.mark.usefixtures("migrated_db", "multi_mode")
async def test_deactivated_account_cannot_be_invited(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    bob = await _register(client, "bob")
    user = (await db_session.execute(select(User).where(User.id == UUID(bob["id"])))).scalar_one()
    user.is_active = False
    await db_session.commit()

    await _register(client, "alice")
    resp = await client.post(
        "/api/v1/users/invites", json={"email": bob["email"], "role": "member"}
    )
    assert resp.status_code == 409
    assert resp.json()["detail"] == "This email belongs to a deactivated account"


@pytest.mark.usefixtures("migrated_db", "multi_mode")
async def test_new_email_invite_reports_no_existing_account(client: AsyncClient) -> None:
    await _register(client, "alice")
    token = await _invite(client, f"fresh-{uuid4().hex[:8]}@ganek-ci.dev")
    info = await client.get(f"/api/v1/public/invites/{token}")
    assert info.status_code == 200
    assert info.json()["existing_account"] is False
