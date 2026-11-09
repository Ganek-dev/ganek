"""Sign-in methods on the Account page (card "SSO + multi-company user
membership", slice 12): /auth/me says whether a Google or SSO identity is
linked, and the signed-in person can unlink one as long as another way to
sign in remains."""

from typing import Any
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models import User
from tests.db import database_reachable

pytestmark = pytest.mark.skipif(
    not database_reachable(),
    reason="database required (start postgres or use CI)",
)

PASSWORD = "a-long-secure-password"
ISSUER = "https://idp.ganek-ci.dev/realms/acme"


@pytest.fixture(autouse=True)
def multi_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    # every test registers its own company
    monkeypatch.setattr(settings, "mode", "multi")


async def _register(client: AsyncClient) -> dict[str, Any]:
    email = f"methods-{uuid4().hex[:8]}@ganek-ci.dev"
    resp = await client.post(
        "/api/v1/auth/register",
        json={
            "company_name": f"Methods Co {uuid4().hex[:6]}",
            "email": email,
            "password": PASSWORD,
        },
    )
    assert resp.status_code == 201, resp.text
    return {"email": email, "id": resp.json()["id"]}


async def _set(db: AsyncSession, user_id: str, **fields: object) -> None:
    user = await db.get(User, UUID(user_id))
    assert user is not None
    for name, value in fields.items():
        setattr(user, name, value)
    await db.commit()


async def _fresh(db: AsyncSession, user_id: str) -> User:
    db.expire_all()
    user = await db.get(User, UUID(user_id))
    assert user is not None
    return user


def _linked(google: bool = True, sso: bool = True) -> dict[str, object]:
    out: dict[str, object] = {}
    if google:
        out["google_sub"] = f"g-{uuid4().hex}"
    if sso:
        out["oidc_issuer"] = ISSUER
        out["oidc_sub"] = f"o-{uuid4().hex}"
    return out


async def test_me_reports_linked_identities(client: AsyncClient, db_session: AsyncSession) -> None:
    me = await _register(client)
    body = (await client.get("/api/v1/auth/me")).json()
    assert body["google_linked"] is False and body["sso_linked"] is False
    assert body["has_password"] is True

    await _set(db_session, me["id"], **_linked())
    body = (await client.get("/api/v1/auth/me")).json()
    assert body["google_linked"] is True and body["sso_linked"] is True
    # the identifiers themselves never leave the server
    assert "google_sub" not in body and "oidc_sub" not in body and "oidc_issuer" not in body


async def test_unlink_google_keeps_password_and_sso(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    me = await _register(client)
    await _set(db_session, me["id"], **_linked())

    resp = await client.delete("/api/v1/auth/sign-in-methods/google")
    assert resp.status_code == 200, resp.text
    assert resp.json()["google_linked"] is False and resp.json()["sso_linked"] is True
    user = await _fresh(db_session, me["id"])
    assert user.google_sub is None and user.oidc_sub is not None
    assert user.password_hash is not None


async def test_unlink_sso_clears_issuer_and_subject(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    me = await _register(client)
    await _set(db_session, me["id"], **_linked(google=False))

    resp = await client.delete("/api/v1/auth/sign-in-methods/sso")
    assert resp.status_code == 200, resp.text
    assert resp.json()["sso_linked"] is False
    user = await _fresh(db_session, me["id"])
    assert user.oidc_issuer is None and user.oidc_sub is None


async def test_only_way_in_is_refused(client: AsyncClient, db_session: AsyncSession) -> None:
    me = await _register(client)
    await _set(db_session, me["id"], password_hash=None, **_linked(sso=False))

    resp = await client.delete("/api/v1/auth/sign-in-methods/google")
    assert resp.status_code == 409
    assert "only way to sign in" in resp.json()["detail"]
    assert (await _fresh(db_session, me["id"])).google_sub is not None


async def test_passwordless_with_two_identities_keeps_the_last(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    me = await _register(client)
    await _set(db_session, me["id"], password_hash=None, **_linked())

    first = await client.delete("/api/v1/auth/sign-in-methods/sso")
    assert first.status_code == 200, first.text
    assert first.json()["sso_linked"] is False and first.json()["google_linked"] is True

    last = await client.delete("/api/v1/auth/sign-in-methods/google")
    assert last.status_code == 409
    user = await _fresh(db_session, me["id"])
    assert user.google_sub is not None and user.oidc_sub is None


async def test_nothing_linked_is_a_no_op(client: AsyncClient, db_session: AsyncSession) -> None:
    me = await _register(client)
    await _set(db_session, me["id"], password_hash=None, **_linked(google=False))

    # Google was never linked: nothing to refuse, nothing changes
    resp = await client.delete("/api/v1/auth/sign-in-methods/google")
    assert resp.status_code == 200, resp.text
    assert resp.json()["sso_linked"] is True
    assert (await _fresh(db_session, me["id"])).oidc_sub is not None


async def test_unknown_method_and_anonymous(client: AsyncClient) -> None:
    await _register(client)
    assert (await client.delete("/api/v1/auth/sign-in-methods/github")).status_code == 422
    client.cookies.clear()
    assert (await client.delete("/api/v1/auth/sign-in-methods/google")).status_code == 401


async def test_locked_on_the_demo(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    me = await _register(client)
    await _set(db_session, me["id"], **_linked(sso=False))
    monkeypatch.setattr(settings, "demo_mode", True)
    resp = await client.delete("/api/v1/auth/sign-in-methods/google")
    assert resp.status_code == 403
    assert (await _fresh(db_session, me["id"])).google_sub is not None
