"""Generic OIDC sign-in endpoints. The IdP's HTTP surface (discovery and
token exchange) is monkeypatched throughout - these tests exercise our flow
handling, the linking rule and cookie handling."""

import time
from datetime import UTC, datetime
from urllib.parse import parse_qs, urlparse
from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.security import OIDC_FLOW_COOKIE_NAME, create_oidc_flow_token
from app.models import Company, User, UserRole
from app.services import oauth_oidc
from tests.db import database_reachable

pytestmark = pytest.mark.skipif(
    not database_reachable(), reason="database not reachable (start postgres or use CI)"
)

ISSUER = "https://idp.example.com/realms/acme"
META = oauth_oidc.ProviderMetadata(ISSUER, f"{ISSUER}/protocol/auth", f"{ISSUER}/protocol/token")


@pytest.fixture
def oidc_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "oidc_issuer", ISSUER)
    monkeypatch.setattr(settings, "oidc_client_id", "ganek")
    monkeypatch.setattr(settings, "oidc_client_secret", "s3cret")
    monkeypatch.setattr(settings, "oidc_display_name", "Acme SSO")
    monkeypatch.setattr(settings, "oidc_email_domains", "example.com")

    async def discover() -> oauth_oidc.ProviderMetadata:
        return META

    monkeypatch.setattr(oauth_oidc, "discover", discover)


def _claims(email: str, sub: str = "sub-1", **overrides: object) -> dict[str, object]:
    claims: dict[str, object] = {
        "iss": ISSUER,
        "aud": "ganek",
        "exp": time.time() + 600,
        "nonce": "nonce-1",
        "sub": sub,
        "email": email,
        "email_verified": True,
    }
    claims.update(overrides)
    return claims


def _arm_flow(client: AsyncClient, next_path: str | None = None) -> None:
    client.cookies.set(
        OIDC_FLOW_COOKIE_NAME,
        create_oidc_flow_token("state-1", "verifier-1", "nonce-1", next_path=next_path),
    )


def _fake_exchange(monkeypatch: pytest.MonkeyPatch, claims: dict[str, object]) -> None:
    async def exchange(
        meta: oauth_oidc.ProviderMetadata, code: str, code_verifier: str
    ) -> dict[str, object]:
        assert (meta, code, code_verifier) == (META, "c", "verifier-1")
        return claims

    monkeypatch.setattr(oauth_oidc, "exchange_code", exchange)


async def _make_user(
    db: AsyncSession,
    email: str,
    *,
    oidc_sub: str | None = None,
    oidc_issuer: str | None = ISSUER,
    is_active: bool = True,
) -> User:
    company = Company(slug=f"oc-{uuid4().hex[:8]}", name="OIDC Cases Co")
    db.add(company)
    await db.flush()
    user = User(
        company_id=company.id,
        email=email,
        password_hash="x",
        role=UserRole.ADMIN,
        oidc_issuer=oidc_issuer if oidc_sub else None,
        oidc_sub=oidc_sub,
        is_active=is_active,
    )
    db.add(user)
    await db.commit()
    return user


async def _fresh(db: AsyncSession, user: User) -> User:
    row = (await db.execute(select(User).where(User.id == user.id))).scalar_one()
    await db.refresh(row)
    return row


async def test_providers_oidc_off_by_default(client: AsyncClient) -> None:
    body = (await client.get("/api/v1/auth/providers")).json()
    assert body["oidc"] is False
    assert "oidc_name" not in body


@pytest.mark.usefixtures("oidc_configured")
async def test_providers_oidc_on_with_its_name(client: AsyncClient) -> None:
    body = (await client.get("/api/v1/auth/providers")).json()
    assert (body["oidc"], body["oidc_name"]) == (True, "Acme SSO")


async def test_start_and_callback_404_when_unconfigured(client: AsyncClient) -> None:
    assert (await client.get("/api/v1/auth/oidc/start")).status_code == 404
    assert (await client.get("/api/v1/auth/oidc/callback?code=c&state=s")).status_code == 404


@pytest.mark.usefixtures("oidc_configured")
async def test_start_redirects_to_the_idp_with_a_flow_cookie(client: AsyncClient) -> None:
    resp = await client.get("/api/v1/auth/oidc/start?next=/invite/abc")
    assert resp.status_code == 302
    location = urlparse(resp.headers["location"])
    assert f"{location.scheme}://{location.hostname}{location.path}" == META.authorization_endpoint
    query = parse_qs(location.query)
    assert query["client_id"] == ["ganek"]
    assert query["scope"] == ["openid email"]
    assert query["code_challenge_method"] == ["S256"]
    assert query["redirect_uri"] == [f"{settings.public_base_url}/api/v1/auth/oidc/callback"]
    set_cookie = "; ".join(resp.headers.get_list("set-cookie"))
    assert OIDC_FLOW_COOKIE_NAME in set_cookie
    assert "HttpOnly" in set_cookie and "Path=/api/v1/auth/oidc" in set_cookie


@pytest.mark.usefixtures("oidc_configured")
async def test_start_discovery_failure_returns_to_login(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def broken() -> oauth_oidc.ProviderMetadata:
        raise oauth_oidc.OidcError("down")

    monkeypatch.setattr(oauth_oidc, "discover", broken)
    resp = await client.get("/api/v1/auth/oidc/start")
    assert resp.headers["location"] == "/login?error=oidc-failed"


@pytest.mark.usefixtures("oidc_configured", "migrated_db")
async def test_callback_cancelled_returns_to_login_silently(client: AsyncClient) -> None:
    _arm_flow(client)
    resp = await client.get("/api/v1/auth/oidc/callback?error=access_denied")
    assert resp.headers["location"] == "/login"


@pytest.mark.usefixtures("oidc_configured", "migrated_db")
async def test_callback_state_mismatch_or_no_cookie(client: AsyncClient) -> None:
    resp = await client.get("/api/v1/auth/oidc/callback?code=c&state=state-1")
    assert resp.headers["location"] == "/login?error=oidc-failed"
    _arm_flow(client)
    resp = await client.get("/api/v1/auth/oidc/callback?code=c&state=other")
    assert resp.headers["location"] == "/login?error=oidc-failed"


@pytest.mark.usefixtures("oidc_configured", "migrated_db")
async def test_callback_bad_claims_fail(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _fake_exchange(monkeypatch, _claims("x@example.com", nonce="replayed"))
    _arm_flow(client)
    resp = await client.get("/api/v1/auth/oidc/callback?code=c&state=state-1")
    assert resp.headers["location"] == "/login?error=oidc-failed"
    assert (await client.get("/api/v1/auth/me")).status_code == 401


@pytest.mark.usefixtures("oidc_configured", "migrated_db")
async def test_callback_known_subject_signs_in(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    email = f"sub-{uuid4().hex[:8]}@example.org"
    sub = f"sub-{uuid4().hex}"
    await _make_user(db_session, email, oidc_sub=sub)
    # the email at the IdP may have changed since linking: the subject decides
    _fake_exchange(monkeypatch, _claims("renamed@example.com", sub=sub))
    _arm_flow(client)
    resp = await client.get("/api/v1/auth/oidc/callback?code=c&state=state-1")
    assert resp.headers["location"] == "/admin"
    me = await client.get("/api/v1/auth/me")
    assert me.json()["email"] == email


@pytest.mark.usefixtures("oidc_configured", "migrated_db")
async def test_callback_same_subject_at_another_issuer_does_not_sign_in(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    sub = f"sub-{uuid4().hex}"
    await _make_user(
        db_session,
        f"old-{uuid4().hex[:8]}@example.com",
        oidc_sub=sub,
        oidc_issuer="https://old.test",
    )
    _fake_exchange(monkeypatch, _claims(f"nobody-{uuid4().hex[:8]}@example.com", sub=sub))
    _arm_flow(client)
    resp = await client.get("/api/v1/auth/oidc/callback?code=c&state=state-1")
    assert resp.headers["location"] == "/login?error=oidc-no-account"


@pytest.mark.usefixtures("oidc_configured", "migrated_db")
async def test_callback_verified_trusted_domain_links_and_signs_in(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    email = f"link-{uuid4().hex[:8]}@example.com"
    user = await _make_user(db_session, email)
    sub = f"sub-{uuid4().hex}"
    _fake_exchange(monkeypatch, _claims(email, sub=sub))
    _arm_flow(client)
    resp = await client.get("/api/v1/auth/oidc/callback?code=c&state=state-1")
    assert resp.headers["location"] == "/admin"
    linked = await _fresh(db_session, user)
    assert (linked.oidc_issuer, linked.oidc_sub) == (ISSUER, sub)
    assert linked.last_login_at is not None


@pytest.mark.parametrize(
    "overrides",
    [{"email_verified": False}, {"email_verified": None}],
)
@pytest.mark.usefixtures("oidc_configured", "migrated_db")
async def test_callback_unverified_email_bounces_to_password(
    client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    overrides: dict[str, object],
) -> None:
    email = f"unv-{uuid4().hex[:8]}@example.com"
    user = await _make_user(db_session, email)
    _fake_exchange(monkeypatch, _claims(email, sub=f"sub-{uuid4().hex}", **overrides))
    _arm_flow(client, next_path="/invite/abc")
    resp = await client.get("/api/v1/auth/oidc/callback?code=c&state=state-1")
    assert resp.headers["location"] == "/login?error=use-password&next=%2Finvite%2Fabc"
    assert (await _fresh(db_session, user)).oidc_sub is None


@pytest.mark.usefixtures("oidc_configured", "migrated_db")
async def test_callback_untrusted_domain_never_links(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An IdP with open self-registration must not take over an account on
    a domain the operator did not list (the classic OIDC takeover)."""
    email = f"victim-{uuid4().hex[:8]}@gmail.com"
    user = await _make_user(db_session, email)
    _fake_exchange(monkeypatch, _claims(email, sub=f"sub-{uuid4().hex}"))
    _arm_flow(client)
    resp = await client.get("/api/v1/auth/oidc/callback?code=c&state=state-1")
    assert resp.headers["location"] == "/login?error=use-password"
    assert (await _fresh(db_session, user)).oidc_sub is None
    assert (await client.get("/api/v1/auth/me")).status_code == 401


@pytest.mark.usefixtures("oidc_configured", "migrated_db")
async def test_callback_never_repoints_an_already_linked_account(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    email = f"taken-{uuid4().hex[:8]}@example.com"
    original = f"sub-{uuid4().hex}"
    user = await _make_user(db_session, email, oidc_sub=original)
    _fake_exchange(monkeypatch, _claims(email, sub=f"sub-{uuid4().hex}"))
    _arm_flow(client)
    resp = await client.get("/api/v1/auth/oidc/callback?code=c&state=state-1")
    assert resp.headers["location"] == "/login?error=use-password"
    assert (await _fresh(db_session, user)).oidc_sub == original


@pytest.mark.usefixtures("oidc_configured", "migrated_db")
async def test_callback_unknown_identity_has_no_account(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _fake_exchange(monkeypatch, _claims(f"new-{uuid4().hex[:8]}@example.com"))
    _arm_flow(client)
    resp = await client.get("/api/v1/auth/oidc/callback?code=c&state=state-1")
    assert resp.headers["location"] == "/login?error=oidc-no-account"


@pytest.mark.usefixtures("oidc_configured", "migrated_db")
async def test_callback_inactive_user(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    sub = f"sub-{uuid4().hex}"
    await _make_user(
        db_session, f"off-{uuid4().hex[:8]}@example.com", oidc_sub=sub, is_active=False
    )
    _fake_exchange(monkeypatch, _claims("off@example.com", sub=sub))
    _arm_flow(client)
    resp = await client.get("/api/v1/auth/oidc/callback?code=c&state=state-1")
    assert resp.headers["location"] == "/login?error=account-disabled"


@pytest.mark.usefixtures("oidc_configured", "migrated_db")
async def test_callback_returns_to_the_invite(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    sub = f"sub-{uuid4().hex}"
    await _make_user(db_session, f"inv-{uuid4().hex[:8]}@example.com", oidc_sub=sub)
    _fake_exchange(monkeypatch, _claims("inv@example.com", sub=sub))
    _arm_flow(client, next_path="/invite/abc.def-1")
    resp = await client.get("/api/v1/auth/oidc/callback?code=c&state=state-1")
    assert resp.headers["location"] == "/invite/abc.def-1"
    assert (await client.get("/api/v1/auth/me")).status_code == 200


@pytest.mark.usefixtures("oidc_configured", "migrated_db")
async def test_callback_with_2fa_goes_to_the_code_step(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    sub = f"sub-{uuid4().hex}"
    user = await _make_user(db_session, f"mfa-{uuid4().hex[:8]}@example.com", oidc_sub=sub)
    user.totp_secret = "enabled-for-this-test"  # noqa: S105 - mfa_service.enabled only checks presence
    user.totp_enabled_at = datetime.now(UTC)
    await db_session.commit()
    _fake_exchange(monkeypatch, _claims("mfa@example.com", sub=sub))
    _arm_flow(client, next_path="/invite/abc")
    resp = await client.get("/api/v1/auth/oidc/callback?code=c&state=state-1")
    location = urlparse(resp.headers["location"])
    assert location.path == "/login"
    query = parse_qs(location.query)
    assert query["mfa"] and query["next"] == ["/invite/abc"]
    assert (await client.get("/api/v1/auth/me")).status_code == 401
