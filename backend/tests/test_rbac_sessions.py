from uuid import uuid4

import pytest
from httpx import AsyncClient

from app.core import lockout, ratelimit
from app.core.config import settings
from tests.db import database_reachable

pytestmark = pytest.mark.skipif(
    not database_reachable(), reason="database not reachable (start postgres or use CI)"
)


@pytest.fixture
def multi_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "mode", "multi")


async def _register_admin(client: AsyncClient) -> dict[str, str]:
    creds = {
        "email": f"admin-{uuid4().hex[:8]}@ganek-ci.dev",
        "password": "a-long-secure-password",
    }
    resp = await client.post(
        "/api/v1/auth/register", json={"company_name": f"Co {uuid4().hex[:6]}", **creds}
    )
    assert resp.status_code == 201, resp.text
    return creds


@pytest.mark.usefixtures("migrated_db", "multi_mode")
async def test_admin_creates_member_who_lacks_admin_rights(client: AsyncClient) -> None:
    admin = await _register_admin(client)

    # admin creates a member
    member_pw = "member-password-1234"
    member_email = f"member-{uuid4().hex[:8]}@ganek-ci.dev"
    resp = await client.post(
        "/api/v1/users",
        json={"email": member_email, "password": member_pw, "role": "member"},
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["role"] == "member"

    # both users are listed
    users = (await client.get("/api/v1/users")).json()
    assert {u["email"] for u in users} == {admin["email"], member_email}

    # member logs in and is blocked from admin-only actions
    await client.post("/api/v1/auth/logout")
    assert (
        await client.post("/api/v1/auth/login", json={"email": member_email, "password": member_pw})
    ).status_code == 200
    # member cannot list/create users, create questions, delete jobs
    assert (await client.get("/api/v1/users")).status_code == 403
    assert (
        await client.post(
            "/api/v1/questions",
            json={
                "prompt_md": "Company internal question?",
                "options": {"a": "1", "b": "2", "c": "3", "d": "4"},
                "correct_key": "a",
                "tags": ["internal"],
            },
        )
    ).status_code == 403
    # but member CAN do day-to-day work
    assert (await client.get("/api/v1/jobs")).status_code == 200


@pytest.mark.usefixtures("migrated_db", "multi_mode")
async def test_cannot_remove_last_admin(client: AsyncClient) -> None:
    await _register_admin(client)
    me = (await client.get("/api/v1/auth/me")).json()
    resp = await client.patch(f"/api/v1/users/{me['id']}", json={"role": "member"})
    assert resp.status_code == 409  # would orphan the company


@pytest.mark.usefixtures("migrated_db", "multi_mode")
async def test_password_change_invalidates_old_sessions(client: AsyncClient) -> None:
    creds = await _register_admin(client)
    # this client's cookie is a valid session
    assert (await client.get("/api/v1/auth/me")).status_code == 200

    # a SECOND client logs in as the same user (separate session cookie)
    async with AsyncClient(transport=client._transport, base_url="http://test") as other:
        assert (await other.post("/api/v1/auth/login", json=creds)).status_code == 200
        assert (await other.get("/api/v1/auth/me")).status_code == 200

        # change password on the first client
        resp = await client.post(
            "/api/v1/auth/change-password",
            json={
                "current_password": creds["password"],
                "new_password": "a-different-secure-pw",
            },
        )
        assert resp.status_code == 204
        # the first client stays logged in (cookie re-issued)
        assert (await client.get("/api/v1/auth/me")).status_code == 200
        # the OTHER session is now invalid
        assert (await other.get("/api/v1/auth/me")).status_code == 401


@pytest.mark.usefixtures("migrated_db", "multi_mode")
async def test_deactivated_user_is_locked_out(client: AsyncClient) -> None:
    admin = await _register_admin(client)
    member_pw = "member-password-1234"
    member_email = f"member-{uuid4().hex[:8]}@ganek-ci.dev"
    member = (
        await client.post(
            "/api/v1/users",
            json={"email": member_email, "password": member_pw, "role": "member"},
        )
    ).json()

    # member has a live session
    await client.post("/api/v1/auth/logout")
    async with AsyncClient(transport=client._transport, base_url="http://test") as m:
        assert (
            await m.post("/api/v1/auth/login", json={"email": member_email, "password": member_pw})
        ).status_code == 200
        assert (await m.get("/api/v1/auth/me")).status_code == 200

        # admin (back on the main client) deactivates the member
        assert (await client.post("/api/v1/auth/login", json=admin)).status_code == 200
        assert (
            await client.patch(f"/api/v1/users/{member['id']}", json={"is_active": False})
        ).status_code == 200

        # member's live session dies immediately, and they can't log back in
        assert (await m.get("/api/v1/auth/me")).status_code == 401
        assert (
            await m.post("/api/v1/auth/login", json={"email": member_email, "password": member_pw})
        ).status_code == 401


@pytest.mark.usefixtures("migrated_db", "multi_mode")
async def test_account_lockout_after_repeated_failures(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "lockout_enabled", True)
    monkeypatch.setattr(settings, "lockout_max_attempts", 3)
    monkeypatch.setattr(ratelimit, "_redis_broken", True)  # deterministic memory path
    monkeypatch.setattr(settings, "rate_limit_enabled", False)  # isolate lockout from rate limit
    ratelimit._memory.clear()

    creds = await _register_admin(client)
    await client.post("/api/v1/auth/logout")
    for _ in range(3):
        resp = await client.post(
            "/api/v1/auth/login", json={"email": creds["email"], "password": "wrong-pw-here"}
        )
        assert resp.status_code == 401
    # now locked — even the CORRECT password is refused with 423
    resp = await client.post("/api/v1/auth/login", json=creds)
    assert resp.status_code == 423
    await lockout.clear(creds["email"])
