"""Google OAuth endpoints. Google's HTTP surface is monkeypatched throughout —
these tests exercise our flow handling, linking rules, and cookie handling."""

import time
from urllib.parse import parse_qs, urlparse
from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.security import (
    GOOGLE_FLOW_COOKIE_NAME,
    create_google_flow_token,
    create_google_signup_token,
    create_invite_token,
)
from app.models import Company, User, UserInvite, UserRole
from app.services import oauth_google
from tests.db import database_reachable

pytestmark = pytest.mark.skipif(
    not database_reachable(), reason="database not reachable (start postgres or use CI)"
)


@pytest.fixture
def google_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "google_client_id", "test-client-id")
    monkeypatch.setattr(settings, "google_client_secret", "test-client-secret")


async def test_providers_google_off_by_default(client: AsyncClient) -> None:
    resp = await client.get("/api/v1/auth/providers")
    assert resp.status_code == 200
    assert resp.json() == {"google": False}


@pytest.mark.usefixtures("google_configured")
async def test_providers_google_on_when_configured(client: AsyncClient) -> None:
    resp = await client.get("/api/v1/auth/providers")
    assert resp.json() == {"google": True}


def _claims(
    email: str, sub: str = "sub-1", nonce: str = "nonce-1", **overrides: object
) -> dict[str, object]:
    claims: dict[str, object] = {
        "iss": "https://accounts.google.com",
        "aud": "test-client-id",
        "exp": time.time() + 600,
        "nonce": nonce,
        "sub": sub,
        "email": email,
        "email_verified": True,
    }
    claims.update(overrides)
    return claims


def _arm_flow(
    client: AsyncClient,
    state: str = "state-1",
    nonce: str = "nonce-1",
    invite: str | None = None,
) -> None:
    client.cookies.set(
        GOOGLE_FLOW_COOKIE_NAME,
        create_google_flow_token(state, "verifier-1", nonce, invite=invite),
    )


def _fake_exchange(claims: dict[str, object]) -> object:
    async def exchange(code: str, code_verifier: str) -> dict[str, object]:
        assert code_verifier == "verifier-1"
        return claims

    return exchange


async def _make_user(
    db: AsyncSession,
    email: str,
    *,
    google_sub: str | None = None,
    password_hash: str | None = "x",  # noqa: S107 - placeholder hash, not a secret
    is_active: bool = True,
) -> User:
    company = Company(slug=f"gc-{uuid4().hex[:8]}", name="Google Cases Co")
    db.add(company)
    await db.flush()
    user = User(
        company_id=company.id,
        email=email,
        password_hash=password_hash,
        role=UserRole.ADMIN,
        google_sub=google_sub,
        is_active=is_active,
    )
    db.add(user)
    await db.commit()
    return user


async def test_start_404_when_unconfigured(client: AsyncClient) -> None:
    resp = await client.get("/api/v1/auth/google/start")
    assert resp.status_code == 404


@pytest.mark.usefixtures("google_configured")
async def test_start_redirects_to_google_with_flow_cookie(client: AsyncClient) -> None:
    resp = await client.get("/api/v1/auth/google/start")
    assert resp.status_code == 302
    location = urlparse(resp.headers["location"])
    assert location.hostname == "accounts.google.com"
    query = parse_qs(location.query)
    assert query["code_challenge_method"] == ["S256"]
    assert query["prompt"] == ["select_account"]
    assert GOOGLE_FLOW_COOKIE_NAME in resp.cookies


@pytest.mark.usefixtures("google_configured", "migrated_db")
async def test_callback_cancelled_returns_to_login_silently(client: AsyncClient) -> None:
    _arm_flow(client)
    resp = await client.get("/api/v1/auth/google/callback?error=access_denied")
    assert resp.status_code == 302
    assert resp.headers["location"] == "/login"


@pytest.mark.usefixtures("google_configured", "migrated_db")
async def test_callback_state_mismatch(client: AsyncClient) -> None:
    _arm_flow(client, state="state-1")
    resp = await client.get("/api/v1/auth/google/callback?code=c&state=WRONG")
    assert resp.status_code == 302
    assert resp.headers["location"] == "/login?error=google-failed"


@pytest.mark.usefixtures("google_configured", "migrated_db")
async def test_callback_unknown_identity_goes_to_setup(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    email = f"new-{uuid4().hex[:8]}@gmail.com"
    monkeypatch.setattr(oauth_google, "exchange_code", _fake_exchange(_claims(email)))
    _arm_flow(client)
    resp = await client.get("/api/v1/auth/google/callback?code=c&state=state-1")
    assert resp.status_code == 302
    assert resp.headers["location"].startswith("/setup?gs=")


@pytest.mark.usefixtures("google_configured", "migrated_db")
async def test_callback_sub_match_logs_in(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    email = f"sub-{uuid4().hex[:8]}@example.com"
    sub = f"sub-{uuid4().hex}"
    await _make_user(db_session, email, google_sub=sub)
    monkeypatch.setattr(oauth_google, "exchange_code", _fake_exchange(_claims(email, sub=sub)))
    _arm_flow(client)
    resp = await client.get("/api/v1/auth/google/callback?code=c&state=state-1")
    assert resp.status_code == 302
    assert resp.headers["location"] == "/admin"
    me = await client.get("/api/v1/auth/me")
    assert me.status_code == 200
    assert me.json()["email"] == email


@pytest.mark.usefixtures("google_configured", "migrated_db")
async def test_callback_gmail_match_links_and_notifies(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.services import email as email_service

    email = f"link-{uuid4().hex[:8]}@gmail.com"
    user = await _make_user(db_session, email)
    sub = f"sub-{uuid4().hex}"
    sent: list[str] = []
    monkeypatch.setattr(oauth_google, "exchange_code", _fake_exchange(_claims(email, sub=sub)))
    monkeypatch.setattr(
        email_service, "send_google_linked", lambda *, to, company_name: sent.append(to)
    )
    _arm_flow(client)
    resp = await client.get("/api/v1/auth/google/callback?code=c&state=state-1")
    assert resp.headers["location"] == "/admin"
    assert sent == [email]
    linked = (await db_session.execute(select(User).where(User.id == user.id))).scalar_one()
    await db_session.refresh(linked)
    assert linked.google_sub == sub


@pytest.mark.usefixtures("google_configured", "migrated_db")
async def test_callback_nonauthoritative_email_bounces_to_password(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    email = f"corp-{uuid4().hex[:8]}@corp.example"
    user = await _make_user(db_session, email)
    # verified but non-gmail and no hd claim: Google is not authoritative
    monkeypatch.setattr(oauth_google, "exchange_code", _fake_exchange(_claims(email)))
    _arm_flow(client)
    resp = await client.get("/api/v1/auth/google/callback?code=c&state=state-1")
    assert resp.headers["location"] == "/login?error=use-password"
    fresh = (await db_session.execute(select(User).where(User.id == user.id))).scalar_one()
    await db_session.refresh(fresh)
    assert fresh.google_sub is None


@pytest.mark.usefixtures("google_configured", "migrated_db")
async def test_callback_inactive_user(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    email = f"off-{uuid4().hex[:8]}@gmail.com"
    sub = f"sub-{uuid4().hex}"
    await _make_user(db_session, email, google_sub=sub, is_active=False)
    monkeypatch.setattr(oauth_google, "exchange_code", _fake_exchange(_claims(email, sub=sub)))
    _arm_flow(client)
    resp = await client.get("/api/v1/auth/google/callback?code=c&state=state-1")
    assert resp.headers["location"] == "/login?error=account-disabled"


@pytest.mark.usefixtures("google_configured", "migrated_db")
async def test_signup_completes_and_sets_session(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "mode", "multi")
    email = f"founder-{uuid4().hex[:8]}@gmail.com"
    token = create_google_signup_token(f"sub-{uuid4().hex}", email)
    resp = await client.post(
        "/api/v1/auth/google/signup",
        json={"token": token, "company_name": f"NewCo {uuid4().hex[:6]}"},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["email"] == email
    assert body["has_password"] is False
    me = await client.get("/api/v1/auth/me")
    assert me.status_code == 200


@pytest.mark.usefixtures("google_configured", "migrated_db")
async def test_signup_registration_closed_in_single_mode(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "mode", "single")
    await _make_user(db_session, f"existing-{uuid4().hex[:8]}@gmail.com")  # a company exists
    token = create_google_signup_token("sub-x", f"late-{uuid4().hex[:8]}@gmail.com")
    resp = await client.post(
        "/api/v1/auth/google/signup", json={"token": token, "company_name": "Late Co"}
    )
    assert resp.status_code == 409


@pytest.mark.usefixtures("google_configured", "migrated_db")
async def test_signup_bad_token_is_410(client: AsyncClient) -> None:
    resp = await client.post(
        "/api/v1/auth/google/signup", json={"token": "garbage", "company_name": "X"}
    )
    assert resp.status_code == 410


async def _make_invite(
    db: AsyncSession, email: str, *, expired: bool = False
) -> tuple[UserInvite, str]:
    from datetime import UTC, datetime, timedelta

    company = Company(slug=f"iv-{uuid4().hex[:8]}", name="Invite Co")
    db.add(company)
    await db.flush()
    invite = UserInvite(
        company_id=company.id,
        email=email,
        role=UserRole.MEMBER,
        expires_at=datetime.now(UTC) + (timedelta(days=-1) if expired else timedelta(days=7)),
    )
    db.add(invite)
    await db.commit()
    await db.refresh(invite)
    return invite, create_invite_token(invite.id)


@pytest.mark.usefixtures("google_configured", "migrated_db")
async def test_invite_accept_via_google(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    email = f"inv-{uuid4().hex[:8]}@gmail.com"
    sub = f"sub-{uuid4().hex}"
    invite, token = await _make_invite(db_session, email)
    monkeypatch.setattr(oauth_google, "exchange_code", _fake_exchange(_claims(email, sub=sub)))
    _arm_flow(client, invite=token)
    resp = await client.get("/api/v1/auth/google/callback?code=c&state=state-1")
    assert resp.status_code == 302
    assert resp.headers["location"] == "/admin"

    me = await client.get("/api/v1/auth/me")
    assert me.status_code == 200
    assert me.json()["email"] == email
    assert me.json()["has_password"] is False
    gone = (
        await db_session.execute(select(UserInvite).where(UserInvite.id == invite.id))
    ).scalar_one_or_none()
    assert gone is None


@pytest.mark.usefixtures("google_configured", "migrated_db")
async def test_invite_accept_rejects_email_mismatch(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, token = await _make_invite(db_session, f"inv-{uuid4().hex[:8]}@corp.dev")
    monkeypatch.setattr(oauth_google, "exchange_code", _fake_exchange(_claims("other@gmail.com")))
    _arm_flow(client, invite=token)
    resp = await client.get("/api/v1/auth/google/callback?code=c&state=state-1")
    assert resp.headers["location"] == f"/invite/{token}?error=google-email-mismatch"


@pytest.mark.usefixtures("google_configured", "migrated_db")
async def test_invite_accept_rejects_unverified_email(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    email = f"inv-{uuid4().hex[:8]}@corp.dev"
    _, token = await _make_invite(db_session, email)
    monkeypatch.setattr(
        oauth_google,
        "exchange_code",
        _fake_exchange(_claims(email, email_verified=False)),
    )
    _arm_flow(client, invite=token)
    resp = await client.get("/api/v1/auth/google/callback?code=c&state=state-1")
    assert resp.headers["location"] == f"/invite/{token}?error=google-email-mismatch"


@pytest.mark.usefixtures("google_configured", "migrated_db")
async def test_invite_accept_expired_invite(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    email = f"inv-{uuid4().hex[:8]}@gmail.com"
    _, token = await _make_invite(db_session, email, expired=True)
    monkeypatch.setattr(oauth_google, "exchange_code", _fake_exchange(_claims(email)))
    _arm_flow(client, invite=token)
    resp = await client.get("/api/v1/auth/google/callback?code=c&state=state-1")
    assert resp.headers["location"] == f"/invite/{token}"


@pytest.mark.usefixtures("google_configured", "migrated_db")
async def test_invite_accept_unknown_invite(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(oauth_google, "exchange_code", _fake_exchange(_claims("x@gmail.com")))
    _arm_flow(client, invite="not-a-real-invite")
    resp = await client.get("/api/v1/auth/google/callback?code=c&state=state-1")
    assert resp.headers["location"] == "/invite/not-a-real-invite?error=google-invalid"
