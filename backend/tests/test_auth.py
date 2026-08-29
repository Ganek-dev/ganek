from collections.abc import Callable
from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models import Company, User, UserRole
from tests.db import database_reachable

pytestmark = pytest.mark.skipif(
    not database_reachable(), reason="database not reachable (start postgres or use CI)"
)


def _register_payload(**overrides: str) -> dict[str, str]:
    payload = {
        "company_name": f"Acme {uuid4().hex[:6]}",
        "email": f"admin-{uuid4().hex[:8]}@ganek-ci.dev",
        "password": "a-long-secure-password",
    }
    payload.update(overrides)
    return payload


MultiMode = Callable[[], None]


@pytest.fixture
def multi_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "mode", "multi")


@pytest.mark.usefixtures("migrated_db", "multi_mode")
async def test_register_login_me_logout_flow(client: AsyncClient) -> None:
    payload = _register_payload()

    resp = await client.post("/api/v1/auth/register", json=payload)
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["email"] == payload["email"]
    assert body["role"] == "admin"
    assert "password" not in body and "password_hash" not in body

    # session cookie from register works
    resp = await client.get("/api/v1/auth/me")
    assert resp.status_code == 200
    assert resp.json()["email"] == payload["email"]

    resp = await client.post("/api/v1/auth/logout")
    assert resp.status_code == 204
    resp = await client.get("/api/v1/auth/me")
    assert resp.status_code == 401

    # fresh login
    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": payload["email"], "password": payload["password"]},
    )
    assert resp.status_code == 200
    resp = await client.get("/api/v1/auth/me")
    assert resp.status_code == 200


@pytest.mark.usefixtures("migrated_db", "multi_mode")
async def test_login_rejects_wrong_password(client: AsyncClient) -> None:
    payload = _register_payload()
    assert (await client.post("/api/v1/auth/register", json=payload)).status_code == 201
    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": payload["email"], "password": "definitely-wrong-password"},
    )
    assert resp.status_code == 401


@pytest.mark.usefixtures("migrated_db", "multi_mode")
async def test_register_rejects_duplicate_email(client: AsyncClient) -> None:
    payload = _register_payload()
    assert (await client.post("/api/v1/auth/register", json=payload)).status_code == 201
    resp = await client.post(
        "/api/v1/auth/register", json=_register_payload(email=payload["email"])
    )
    assert resp.status_code == 409


@pytest.mark.usefixtures("migrated_db")
async def test_single_mode_registration_closes_after_first_company(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "mode", "multi")
    assert (await client.post("/api/v1/auth/register", json=_register_payload())).status_code == 201
    # DB now has >=1 company; single mode must refuse further registrations
    monkeypatch.setattr(settings, "mode", "single")
    resp = await client.post("/api/v1/auth/register", json=_register_payload())
    assert resp.status_code == 409


async def test_me_requires_auth(client: AsyncClient) -> None:
    resp = await client.get("/api/v1/auth/me")
    assert resp.status_code == 401


@pytest.mark.usefixtures("migrated_db")
async def test_password_login_rejects_google_only_user(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    company = Company(slug=f"go-{uuid4().hex[:8]}", name="Google Only Co")
    db_session.add(company)
    await db_session.flush()
    email = f"go-{uuid4().hex[:8]}@gmail.com"
    user = User(
        company_id=company.id,
        email=email,
        password_hash=None,
        role=UserRole.ADMIN,
        google_sub=f"sub-{uuid4().hex}",
    )
    db_session.add(user)
    await db_session.commit()

    resp = await client.post(
        "/api/v1/auth/login", json={"email": email, "password": "whatever-long"}
    )
    assert resp.status_code == 401


@pytest.fixture
def captured_reset(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, object]]:
    from app.services import email as email_service

    sent: list[dict[str, object]] = []
    monkeypatch.setattr(email_service, "send_password_reset", lambda **kw: sent.append(kw))
    return sent


def _reset_token(sent: list[dict[str, object]]) -> str:
    return str(sent[-1]["reset_url"]).rsplit("token=", 1)[-1]


@pytest.mark.usefixtures("migrated_db", "multi_mode")
async def test_forgot_password_flow_resets_and_logs_in(
    client: AsyncClient, captured_reset: list[dict[str, object]]
) -> None:
    payload = _register_payload()
    assert (await client.post("/api/v1/auth/register", json=payload)).status_code == 201
    await client.post("/api/v1/auth/logout")

    resp = await client.post("/api/v1/auth/forgot-password", json={"email": payload["email"]})
    assert resp.status_code == 204
    assert len(captured_reset) == 1
    assert captured_reset[0]["to"] == payload["email"]
    assert "/reset?token=" in str(captured_reset[0]["reset_url"])

    resp = await client.post(
        "/api/v1/auth/reset-password",
        json={"token": _reset_token(captured_reset), "new_password": "a-brand-new-password"},
    )
    assert resp.status_code == 200, resp.text
    # the reset logs the user straight in ...
    assert (await client.get("/api/v1/auth/me")).status_code == 200

    # ... the new password works, the old one is gone
    await client.post("/api/v1/auth/logout")
    old = await client.post(
        "/api/v1/auth/login", json={"email": payload["email"], "password": payload["password"]}
    )
    assert old.status_code == 401
    new = await client.post(
        "/api/v1/auth/login",
        json={"email": payload["email"], "password": "a-brand-new-password"},
    )
    assert new.status_code == 200


@pytest.mark.usefixtures("migrated_db", "multi_mode")
async def test_forgot_password_never_reveals_accounts(
    client: AsyncClient, captured_reset: list[dict[str, object]]
) -> None:
    resp = await client.post(
        "/api/v1/auth/forgot-password",
        json={"email": f"nobody-{uuid4().hex[:8]}@ganek-ci.dev"},
    )
    assert resp.status_code == 204  # indistinguishable from a real account
    assert captured_reset == []


@pytest.mark.usefixtures("migrated_db", "multi_mode")
async def test_reset_token_is_single_use_and_kills_old_sessions(
    client: AsyncClient, captured_reset: list[dict[str, object]]
) -> None:
    payload = _register_payload()
    assert (await client.post("/api/v1/auth/register", json=payload)).status_code == 201
    # keep the registration session cookie around to prove the reset kills it
    assert (await client.get("/api/v1/auth/me")).status_code == 200
    pre_reset_session = client.cookies["ganek_session"]

    assert (
        await client.post("/api/v1/auth/forgot-password", json={"email": payload["email"]})
    ).status_code == 204
    token = _reset_token(captured_reset)
    assert (
        await client.post(
            "/api/v1/auth/reset-password",
            json={"token": token, "new_password": "a-brand-new-password"},
        )
    ).status_code == 200

    # same token again: the version bump retired it
    again = await client.post(
        "/api/v1/auth/reset-password",
        json={"token": token, "new_password": "yet-another-password"},
    )
    assert again.status_code == 400

    # the reset issued a fresh session; the PRE-reset one died with the bump
    assert (await client.get("/api/v1/auth/me")).status_code == 200
    client.cookies.set("ganek_session", pre_reset_session)
    assert (await client.get("/api/v1/auth/me")).status_code == 401


@pytest.mark.usefixtures("migrated_db")
async def test_reset_gives_google_only_user_a_password(
    client: AsyncClient, db_session: AsyncSession, captured_reset: list[dict[str, object]]
) -> None:
    company = Company(slug=f"go-{uuid4().hex[:8]}", name="Google Only Co")
    db_session.add(company)
    await db_session.flush()
    email = f"go-{uuid4().hex[:8]}@gmail.com"
    db_session.add(
        User(
            company_id=company.id,
            email=email,
            password_hash=None,
            role=UserRole.ADMIN,
            google_sub=f"sub-{uuid4().hex}",
        )
    )
    await db_session.commit()

    assert (
        await client.post("/api/v1/auth/forgot-password", json={"email": email})
    ).status_code == 204
    assert (
        await client.post(
            "/api/v1/auth/reset-password",
            json={"token": _reset_token(captured_reset), "new_password": "a-brand-new-password"},
        )
    ).status_code == 200
    await client.post("/api/v1/auth/logout")
    assert (
        await client.post(
            "/api/v1/auth/login", json={"email": email, "password": "a-brand-new-password"}
        )
    ).status_code == 200


@pytest.mark.usefixtures("migrated_db")
async def test_forgot_password_skips_deactivated_accounts(
    client: AsyncClient, db_session: AsyncSession, captured_reset: list[dict[str, object]]
) -> None:
    company = Company(slug=f"da-{uuid4().hex[:8]}", name="Deactivated Co")
    db_session.add(company)
    await db_session.flush()
    email = f"gone-{uuid4().hex[:8]}@ganek-ci.dev"
    db_session.add(
        User(
            company_id=company.id,
            email=email,
            password_hash="x",
            role=UserRole.MEMBER,
            is_active=False,
        )
    )
    await db_session.commit()

    assert (
        await client.post("/api/v1/auth/forgot-password", json={"email": email})
    ).status_code == 204
    assert captured_reset == []


@pytest.fixture
def captured_verification(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, object]]:
    from app.services import email as email_service

    sent: list[dict[str, object]] = []
    monkeypatch.setattr(email_service, "send_email_verification", lambda **kw: sent.append(kw))
    return sent


@pytest.fixture
def multi_with_smtp(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "mode", "multi")
    monkeypatch.setattr(settings, "smtp_host", "mail.example.com")


def _verify_token(sent: list[dict[str, object]]) -> str:
    return str(sent[-1]["verify_url"]).rsplit("token=", 1)[-1]


@pytest.mark.usefixtures("migrated_db", "multi_with_smtp")
async def test_multi_mode_signup_requires_email_verification(
    client: AsyncClient, captured_verification: list[dict[str, object]]
) -> None:
    """M5.7 H4: an exposed multi instance must not hand out active companies
    (and branded email) to anyone who types an address."""
    payload = _register_payload()
    resp = await client.post("/api/v1/auth/register", json=payload)
    assert resp.status_code == 201, resp.text
    assert resp.json()["pending_verification"] is True
    assert "set-cookie" not in resp.headers  # no session until the inbox click
    assert len(captured_verification) == 1
    assert captured_verification[0]["to"] == payload["email"]

    # right password, unverified: a 403 that says what to do — not a bare 401
    login = await client.post(
        "/api/v1/auth/login", json={"email": payload["email"], "password": payload["password"]}
    )
    assert login.status_code == 403
    assert "Verify your email" in login.json()["detail"]

    # the inbox click activates and logs in
    verify = await client.post(
        "/api/v1/auth/verify-email", json={"token": _verify_token(captured_verification)}
    )
    assert verify.status_code == 200, verify.text
    assert (await client.get("/api/v1/auth/me")).status_code == 200

    # clicking the emailed link again (stale tab) stays friendly
    again = await client.post(
        "/api/v1/auth/verify-email", json={"token": _verify_token(captured_verification)}
    )
    assert again.status_code == 200

    await client.post("/api/v1/auth/logout")
    assert (
        await client.post(
            "/api/v1/auth/login",
            json={"email": payload["email"], "password": payload["password"]},
        )
    ).status_code == 200


@pytest.mark.usefixtures("migrated_db", "multi_with_smtp")
async def test_resend_verification_is_quiet_and_targeted(
    client: AsyncClient, captured_verification: list[dict[str, object]]
) -> None:
    payload = _register_payload()
    assert (await client.post("/api/v1/auth/register", json=payload)).status_code == 201
    assert len(captured_verification) == 1

    resp = await client.post("/api/v1/auth/resend-verification", json={"email": payload["email"]})
    assert resp.status_code == 204
    assert len(captured_verification) == 2

    # unknown addresses and already-active accounts get the same 204, no email
    assert (
        await client.post(
            "/api/v1/auth/resend-verification",
            json={"email": f"nobody-{uuid4().hex[:8]}@ganek-ci.dev"},
        )
    ).status_code == 204
    assert len(captured_verification) == 2


@pytest.mark.usefixtures("migrated_db", "multi_with_smtp")
async def test_bogus_verification_token_is_rejected(client: AsyncClient) -> None:
    resp = await client.post("/api/v1/auth/verify-email", json={"token": "not-a-token"})
    assert resp.status_code == 400
    assert "request a new one" in resp.json()["detail"]


@pytest.mark.usefixtures("migrated_db")
async def test_single_mode_signup_stays_immediate(
    client: AsyncClient,
    captured_verification: list[dict[str, object]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Single mode closes after the first company — verification would only
    add friction to the self-hoster's one-time setup."""
    monkeypatch.setattr(settings, "smtp_host", "mail.example.com")  # smtp alone must not gate
    payload = _register_payload()
    resp = await client.post("/api/v1/auth/register", json=payload)
    assert resp.status_code in (201, 409)  # 409 = a dev DB already has its company
    if resp.status_code == 201:
        assert resp.json()["pending_verification"] is False
        assert (await client.get("/api/v1/auth/me")).status_code == 200
    assert captured_verification == []


@pytest.mark.usefixtures("migrated_db", "bucket", "multi_with_smtp")
async def test_purge_sweeps_stale_unverified_companies(
    client: AsyncClient,
    db_session: AsyncSession,
    captured_verification: list[dict[str, object]],
) -> None:
    from datetime import UTC, datetime, timedelta

    from sqlalchemy import select, update

    from app.services import retention

    payload = _register_payload()
    assert (await client.post("/api/v1/auth/register", json=payload)).status_code == 201
    user_row = (
        await db_session.execute(select(User).where(User.email == payload["email"]))
    ).scalar_one()
    company_id = user_row.company_id
    await db_session.execute(
        update(Company)
        .where(Company.id == company_id)
        .values(created_at=datetime.now(UTC) - timedelta(days=8))
    )
    await db_session.commit()

    summary = await retention.run_purge(db_session, now=datetime.now(UTC))
    assert summary.unverified_companies >= 1
    db_session.expire_all()
    assert (
        await db_session.execute(select(Company.id).where(Company.id == company_id))
    ).scalar_one_or_none() is None
    # the admin user cascaded away with it
    assert (
        await db_session.execute(select(User.id).where(User.email == payload["email"]))
    ).scalar_one_or_none() is None
