"""Two-factor login and "sign out everywhere" (board card A6)."""

from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from app.core import totp
from app.core.config import settings
from app.core.security import SESSION_COOKIE_NAME
from app.main import app
from tests.db import database_reachable

pytestmark = pytest.mark.skipif(
    not database_reachable(), reason="database not reachable (start postgres or use CI)"
)

PASSWORD = "a-long-secure-password"


@pytest.fixture
def multi_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "mode", "multi")


async def _register(client: AsyncClient) -> dict[str, str]:
    creds = {"email": f"admin-{uuid4().hex[:8]}@ganek-ci.dev", "password": PASSWORD}
    resp = await client.post(
        "/api/v1/auth/register", json={"company_name": f"MFA Co {uuid4().hex[:6]}", **creds}
    )
    assert resp.status_code == 201, resp.text
    return creds


async def _enable(client: AsyncClient) -> tuple[str, list[str]]:
    """Enrol + confirm as the logged-in user; returns (secret, recovery codes)."""
    enrol = await client.post("/api/v1/auth/mfa/enrol")
    assert enrol.status_code == 200, enrol.text
    secret = enrol.json()["secret"]
    assert enrol.json()["otpauth_uri"].startswith("otpauth://totp/Ganek%3A")
    confirm = await client.post(
        "/api/v1/auth/mfa/confirm", json={"code": totp._code_at(secret, totp.current_step())}
    )
    assert confirm.status_code == 200, confirm.text
    codes = confirm.json()["recovery_codes"]
    assert len(codes) == totp.RECOVERY_CODE_COUNT
    return secret, codes


@pytest.mark.usefixtures("migrated_db", "multi_mode")
async def test_enrolment_needs_a_valid_code_and_reports_state(client: AsyncClient) -> None:
    await _register(client)
    assert (await client.get("/api/v1/auth/me")).json()["mfa_enabled"] is False
    assert (await client.post("/api/v1/auth/mfa/enrol")).status_code == 200
    wrong = await client.post("/api/v1/auth/mfa/confirm", json={"code": "000000"})
    assert wrong.status_code in (400,)  # 1 in 10^6 chance of a collision, accepted
    assert (await client.get("/api/v1/auth/me")).json()["mfa_enabled"] is False
    secret, _ = await _enable(client)
    me = (await client.get("/api/v1/auth/me")).json()
    assert me["mfa_enabled"] is True
    assert me["recovery_codes_left"] == totp.RECOVERY_CODE_COUNT
    assert (await client.post("/api/v1/auth/mfa/enrol")).status_code == 409


@pytest.mark.usefixtures("migrated_db", "multi_mode")
async def test_login_requires_the_code_and_a_wrong_code_locks(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    creds = await _register(client)
    secret, codes = await _enable(client)
    await client.post("/api/v1/auth/logout")

    first = await client.post("/api/v1/auth/login", json=creds)
    assert first.status_code == 200, first.text
    body = first.json()
    assert body["mfa_required"] is True and body["mfa_token"]
    assert SESSION_COOKIE_NAME not in client.cookies  # no session yet
    assert (await client.get("/api/v1/auth/me")).status_code == 401

    bad = await client.post(
        "/api/v1/auth/mfa", json={"mfa_token": body["mfa_token"], "code": "000000"}
    )
    assert bad.status_code == 401
    assert bad.json()["detail"] == "Wrong code"

    # the confirmation code consumed the current step (replay guard), so the
    # login uses the next one; the drift window accepts it
    login_code = totp._code_at(secret, totp.current_step() + 1)
    good = await client.post(
        "/api/v1/auth/mfa", json={"mfa_token": body["mfa_token"], "code": login_code}
    )
    assert good.status_code == 200, good.text
    assert good.json()["mfa_required"] is False
    assert (await client.get("/api/v1/auth/me")).status_code == 200

    # the same code never logs in twice (replay inside the window)
    await client.post("/api/v1/auth/logout")
    again = (await client.post("/api/v1/auth/login", json=creds)).json()
    replay = await client.post(
        "/api/v1/auth/mfa", json={"mfa_token": again["mfa_token"], "code": login_code}
    )
    assert replay.status_code == 401

    # wrong codes feed the account lockout
    monkeypatch.setattr(settings, "lockout_max_attempts", 3)
    for _ in range(3):
        await client.post(
            "/api/v1/auth/mfa", json={"mfa_token": again["mfa_token"], "code": "111111"}
        )
    locked = await client.post(
        "/api/v1/auth/mfa", json={"mfa_token": again["mfa_token"], "code": codes[0]}
    )
    assert locked.status_code == 423

    garbage = await client.post("/api/v1/auth/mfa", json={"mfa_token": "nope", "code": "123456"})
    assert garbage.status_code == 401


@pytest.mark.usefixtures("migrated_db", "multi_mode")
async def test_recovery_code_works_once(client: AsyncClient) -> None:
    creds = await _register(client)
    _, codes = await _enable(client)
    await client.post("/api/v1/auth/logout")
    step1 = (await client.post("/api/v1/auth/login", json=creds)).json()
    ok = await client.post(
        "/api/v1/auth/mfa", json={"mfa_token": step1["mfa_token"], "code": codes[3]}
    )
    assert ok.status_code == 200, ok.text
    assert (await client.get("/api/v1/auth/me")).json()["recovery_codes_left"] == (
        totp.RECOVERY_CODE_COUNT - 1
    )
    await client.post("/api/v1/auth/logout")
    step2 = (await client.post("/api/v1/auth/login", json=creds)).json()
    used = await client.post(
        "/api/v1/auth/mfa", json={"mfa_token": step2["mfa_token"], "code": codes[3]}
    )
    assert used.status_code == 401
    fresh = await client.post(
        "/api/v1/auth/mfa", json={"mfa_token": step2["mfa_token"], "code": codes[4]}
    )
    assert fresh.status_code == 200


@pytest.mark.usefixtures("migrated_db", "multi_mode")
async def test_disable_needs_reauthentication(client: AsyncClient) -> None:
    creds = await _register(client)
    await _enable(client)
    assert (
        await client.post("/api/v1/auth/mfa/disable", json={"password": "wrong-password-xx"})
    ).status_code == 400
    assert (await client.get("/api/v1/auth/me")).json()["mfa_enabled"] is True
    assert (
        await client.post("/api/v1/auth/mfa/disable", json={"password": creds["password"]})
    ).status_code == 204
    assert (await client.get("/api/v1/auth/me")).json()["mfa_enabled"] is False
    await client.post("/api/v1/auth/logout")
    plain = await client.post("/api/v1/auth/login", json=creds)
    assert plain.json()["mfa_required"] is False
    assert (await client.get("/api/v1/auth/me")).status_code == 200


@pytest.mark.usefixtures("migrated_db", "multi_mode")
async def test_sign_out_everywhere_kills_other_sessions_but_keeps_this_one(
    client: AsyncClient,
) -> None:
    creds = await _register(client)
    # a second browser
    other = AsyncClient(transport=ASGITransport(app=app), base_url=str(client.base_url))
    async with other:
        assert (await other.post("/api/v1/auth/login", json=creds)).status_code == 200
        assert (await other.get("/api/v1/auth/me")).status_code == 200

        resp = await client.post("/api/v1/auth/sign-out-everywhere")
        assert resp.status_code == 204, resp.text
        assert (await client.get("/api/v1/auth/me")).status_code == 200  # re-issued
        assert (await other.get("/api/v1/auth/me")).status_code == 401  # gone
