"""Team invites (D6): admin invite CRUD + public accept flow."""

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.security import create_invite_token
from app.models import UserInvite
from app.services import email as email_service
from tests.db import database_reachable

pytestmark = pytest.mark.skipif(
    not database_reachable(), reason="database not reachable (start postgres or use CI)"
)


@pytest.fixture
def multi_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "mode", "multi")


async def _register_admin(client: AsyncClient) -> dict[str, str]:
    creds = {
        "email": f"admin-{uuid4().hex[:8]}@vetd-ci.dev",
        "password": "a-long-secure-password",
    }
    resp = await client.post(
        "/api/v1/auth/register", json={"company_name": f"Invite Co {uuid4().hex[:6]}", **creds}
    )
    assert resp.status_code == 201, resp.text
    return creds


async def _create_invite(client: AsyncClient, role: str = "member") -> dict[str, str]:
    email = f"invitee-{uuid4().hex[:8]}@vetd-ci.dev"
    resp = await client.post("/api/v1/users/invites", json={"email": email, "role": role})
    assert resp.status_code == 201, resp.text
    return resp.json()


@pytest.mark.usefixtures("migrated_db", "multi_mode")
async def test_invite_crud_and_conflicts(client: AsyncClient) -> None:
    admin = await _register_admin(client)

    invite = await _create_invite(client)
    listed = (await client.get("/api/v1/users/invites")).json()
    assert [i["id"] for i in listed] == [invite["id"]]
    assert listed[0]["role"] == "member"
    assert listed[0]["expires_at"] > listed[0]["created_at"]

    # duplicate pending invite for the same email is refused
    resp = await client.post(
        "/api/v1/users/invites", json={"email": invite["email"], "role": "admin"}
    )
    assert resp.status_code == 409

    # inviting an email that already has an account is refused
    resp = await client.post(
        "/api/v1/users/invites", json={"email": admin["email"], "role": "member"}
    )
    assert resp.status_code == 409

    # resend pushes the deadline forward
    resent = await client.post(f"/api/v1/users/invites/{invite['id']}/resend")
    assert resent.status_code == 200
    assert resent.json()["expires_at"] >= invite["expires_at"]

    # revoke removes the invite and its token stops resolving
    assert (await client.delete(f"/api/v1/users/invites/{invite['id']}")).status_code == 204
    assert (await client.get("/api/v1/users/invites")).json() == []
    token = create_invite_token(UUID(invite["id"]))
    assert (await client.get(f"/api/v1/public/invites/{token}")).status_code == 404


@pytest.mark.usefixtures("migrated_db", "multi_mode")
async def test_invites_are_admin_only(client: AsyncClient) -> None:
    await _register_admin(client)
    member_email = f"member-{uuid4().hex[:8]}@vetd-ci.dev"
    member_pw = "member-password-1234"
    resp = await client.post(
        "/api/v1/users", json={"email": member_email, "password": member_pw, "role": "member"}
    )
    assert resp.status_code == 201, resp.text

    await client.post("/api/v1/auth/logout")
    resp = await client.post(
        "/api/v1/auth/login", json={"email": member_email, "password": member_pw}
    )
    assert resp.status_code == 200
    assert (await client.get("/api/v1/users/invites")).status_code == 403
    assert (
        await client.post(
            "/api/v1/users/invites", json={"email": "x@vetd-ci.dev", "role": "member"}
        )
    ).status_code == 403


@pytest.mark.usefixtures("migrated_db", "multi_mode")
async def test_invites_are_tenant_scoped(client: AsyncClient) -> None:
    await _register_admin(client)
    invite = await _create_invite(client)
    await client.post("/api/v1/auth/logout")

    # another company's admin can't see or touch it
    await _register_admin(client)
    assert (await client.get("/api/v1/users/invites")).json() == []
    assert (await client.delete(f"/api/v1/users/invites/{invite['id']}")).status_code == 404
    assert (await client.post(f"/api/v1/users/invites/{invite['id']}/resend")).status_code == 404


@pytest.mark.usefixtures("migrated_db", "multi_mode")
async def test_accept_flow_creates_logged_in_user(client: AsyncClient) -> None:
    await _register_admin(client)
    invite = await _create_invite(client, role="admin")
    company_users = (await client.get("/api/v1/users")).json()
    await client.post("/api/v1/auth/logout")

    token = create_invite_token(UUID(invite["id"]))
    info = await client.get(f"/api/v1/public/invites/{token}")
    assert info.status_code == 200
    assert info.json()["email"] == invite["email"]
    assert info.json()["role"] == "admin"
    assert info.json()["company_name"].startswith("Invite Co ")

    resp = await client.post(
        f"/api/v1/public/invites/{token}/accept",
        json={"password": "a-brand-new-password"},
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["email"] == invite["email"]
    assert resp.json()["role"] == "admin"

    # the accept response logged the new user in
    me = await client.get("/api/v1/auth/me")
    assert me.status_code == 200
    assert me.json()["email"] == invite["email"]

    # invite is consumed: token dead, user joined the inviting company
    assert (await client.get(f"/api/v1/public/invites/{token}")).status_code == 404
    assert (
        await client.post(
            f"/api/v1/public/invites/{token}/accept", json={"password": "another-password-1"}
        )
    ).status_code == 404
    users = (await client.get("/api/v1/users")).json()
    assert {u["email"] for u in users} == {u["email"] for u in company_users} | {invite["email"]}
    assert (await client.get("/api/v1/users/invites")).json() == []


@pytest.mark.usefixtures("migrated_db", "multi_mode")
async def test_expired_invite_is_gone_but_replaceable(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _register_admin(client)
    invite = await _create_invite(client)

    row = (
        await db_session.execute(select(UserInvite).where(UserInvite.email == invite["email"]))
    ).scalar_one()
    row.expires_at = datetime.now(UTC) - timedelta(days=1)
    await db_session.commit()

    token = create_invite_token(UUID(invite["id"]))
    assert (await client.get(f"/api/v1/public/invites/{token}")).status_code == 410
    assert (
        await client.post(f"/api/v1/public/invites/{token}/accept", json={"password": "p" * 12})
    ).status_code == 410

    # re-inviting the same email replaces the expired leftover
    resp = await client.post(
        "/api/v1/users/invites", json={"email": invite["email"], "role": "member"}
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["id"] != invite["id"]


@pytest.mark.usefixtures("migrated_db", "multi_mode")
async def test_garbage_invite_token_is_404(client: AsyncClient) -> None:
    assert (await client.get("/api/v1/public/invites/not-a-token")).status_code == 404


def test_team_invite_email_content(monkeypatch: pytest.MonkeyPatch) -> None:
    sent: dict[str, str | None] = {}

    def _capture(*, to: str, subject: str, body: str, html: str | None = None) -> None:
        sent.update({"to": to, "subject": subject, "body": body, "html": html})

    monkeypatch.setattr(email_service, "send_email", _capture)
    email_service.send_team_invite(
        to="dana@vetd-ci.dev",
        company_name="Acme Labs",
        inviter_email="grumpy@vetd-ci.dev",
        role="member",
        invite_url="http://localhost:3000/invite/tok123",
        expires_at=datetime(2026, 8, 2, tzinfo=UTC),
        brand_primary="#7E14FF",
    )
    assert sent["to"] == "dana@vetd-ci.dev"
    assert sent["subject"] == "You're invited to join Acme Labs on vetd"
    assert "grumpy@vetd-ci.dev" in sent["body"]
    assert "Recruiter" in sent["body"]
    assert "http://localhost:3000/invite/tok123" in sent["body"]
    html = sent["html"]
    assert html is not None
    assert "Accept invite" in html and "#7E14FF" in html
