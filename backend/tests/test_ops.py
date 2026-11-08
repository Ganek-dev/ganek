"""Operator plane (board card "Operator plane", first slice): the /ops gate
is a 404 for everyone off the allow-list, and a suspended tenant loses its
public pages, sign-in, sessions and API keys until it is unsuspended."""

from typing import Any
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient

from app.core.config import settings
from app.core.ops import superadmin_ids
from app.core.tenancy import PUBLIC_UNAVAILABLE_DETAIL
from tests.db import database_reachable

PASSWORD = "a-long-secure-password"

db_required = pytest.mark.skipif(
    not database_reachable(), reason="database not reachable (start postgres or use CI)"
)


@pytest.fixture
def multi_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "mode", "multi")


async def _register(client: AsyncClient) -> dict[str, Any]:
    email = f"ops-{uuid4().hex[:8]}@ganek-ci.dev"
    resp = await client.post(
        "/api/v1/auth/register",
        json={"company_name": f"Ops Co {uuid4().hex[:6]}", "email": email, "password": PASSWORD},
    )
    assert resp.status_code == 201, resp.text
    company = (await client.get("/api/v1/company")).json()
    return {"email": email, "id": resp.json()["id"], "slug": company["slug"]}


async def _login(client: AsyncClient, email: str) -> Any:
    await client.post("/api/v1/auth/logout")
    return await client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})


def _ops_calls(company_id: str) -> list[tuple[str, str, dict[str, Any] | None]]:
    return [
        ("GET", "/api/v1/ops/tenants", None),
        ("POST", f"/api/v1/ops/tenants/{company_id}/suspend", {"reason": "x"}),
        ("POST", f"/api/v1/ops/tenants/{company_id}/suspend", {}),
        ("POST", f"/api/v1/ops/tenants/{company_id}/unsuspend", None),
        ("GET", f"/api/v1/ops/tenants/{company_id}/export", None),
    ]


async def _assert_ops_hidden(client: AsyncClient, company_id: str) -> None:
    for method, url, body in _ops_calls(company_id):
        resp = await client.request(method, url, json=body)
        assert resp.status_code == 404, (method, url, resp.status_code, resp.text)
        assert resp.json() == {"detail": "Not Found"}


def test_superadmin_ids_parse_and_skip_garbage(monkeypatch: pytest.MonkeyPatch) -> None:
    a, b = uuid4(), uuid4()
    monkeypatch.setattr(settings, "superadmin_user_ids", f" {a}, not-a-uuid,,{b} ")
    assert superadmin_ids() == frozenset({a, b})
    monkeypatch.setattr(settings, "superadmin_user_ids", "")
    assert superadmin_ids() == frozenset()


@db_required
@pytest.mark.usefixtures("migrated_db", "multi_mode")
async def test_ops_is_404_for_everyone_off_the_allow_list(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    tenant = await _register(client)
    me = await client.get("/api/v1/auth/me")
    company_id = me.json()["company_id"]

    # empty allow-list: even a tenant admin sees no /ops routes
    monkeypatch.setattr(settings, "superadmin_user_ids", "")
    await _assert_ops_hidden(client, company_id)

    # allow-list set to someone else: still a 404, signed in or not
    monkeypatch.setattr(settings, "superadmin_user_ids", str(uuid4()))
    await _assert_ops_hidden(client, company_id)
    await client.post("/api/v1/auth/logout")
    await _assert_ops_hidden(client, company_id)

    # a forged cookie for an allowed id with a stale token version is refused
    monkeypatch.setattr(settings, "superadmin_user_ids", tenant["id"])
    from app.core.security import SESSION_COOKIE_NAME, create_session_token

    client.cookies.set(SESSION_COOKIE_NAME, create_session_token(UUID(tenant["id"]), 999))
    await _assert_ops_hidden(client, company_id)


@db_required
@pytest.mark.usefixtures("migrated_db", "multi_mode")
async def test_suspend_blocks_the_tenant_and_unsuspend_restores_it(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    tenant = await _register(client)
    company_id = (await client.get("/api/v1/auth/me")).json()["company_id"]
    key = await client.post("/api/v1/api-keys", json={"name": "Zap", "scope": "read"})
    assert key.status_code == 201, key.text
    bearer = {"Authorization": f"Bearer {key.json()['secret']}"}
    tenant_cookies = dict(client.cookies)

    operator = await _register(client)
    monkeypatch.setattr(settings, "superadmin_user_ids", operator["id"])

    listed = await client.get("/api/v1/ops/tenants")
    assert listed.status_code == 200, listed.text
    row = next(t for t in listed.json() if t["id"] == company_id)
    assert row["slug"] == tenant["slug"] and row["users"] == 1 and row["jobs"] == 0
    assert row["suspended_at"] is None

    assert (
        await client.post(f"/api/v1/ops/tenants/{company_id}/suspend", json={"reason": ""})
    ).status_code == 422
    assert (
        await client.post(f"/api/v1/ops/tenants/{uuid4()}/suspend", json={"reason": "x"})
    ).status_code == 404
    suspended = await client.post(
        f"/api/v1/ops/tenants/{company_id}/suspend", json={"reason": "Unpaid invoice"}
    )
    assert suspended.status_code == 200, suspended.text
    assert suspended.json()["suspended_at"] is not None
    assert suspended.json()["suspension_reason"] == "Unpaid invoice"

    # public careers page: neutral 503, nothing about why
    page = await client.get(f"/api/v1/public/companies/{tenant['slug']}")
    assert page.status_code == 503
    assert page.json() == {"detail": PUBLIC_UNAVAILABLE_DETAIL}

    # API key and the session issued before the suspension: refused with the reason
    keyed = await client.get("/api/v1/applications", headers=bearer)
    assert keyed.status_code == 403 and "Unpaid invoice" in keyed.json()["detail"]
    operator_cookies = dict(client.cookies)
    client.cookies.clear()
    client.cookies.update(tenant_cookies)
    stale = await client.get("/api/v1/auth/me")
    assert stale.status_code == 403 and "Unpaid invoice" in stale.json()["detail"]

    # sign-in: the right password gets the reason, a wrong one stays a 401
    login = await _login(client, tenant["email"])
    assert login.status_code == 403
    assert login.json()["detail"].startswith("This workspace is suspended: Unpaid invoice")
    wrong = await client.post(
        "/api/v1/auth/login", json={"email": tenant["email"], "password": "wrong-password-123"}
    )
    assert wrong.status_code == 401

    # the operator's own workspace is unaffected
    client.cookies.clear()
    client.cookies.update(operator_cookies)
    assert (await client.get("/api/v1/auth/me")).status_code == 200
    restored = await client.post(f"/api/v1/ops/tenants/{company_id}/unsuspend")
    assert restored.status_code == 200
    assert restored.json()["suspended_at"] is None and restored.json()["suspension_reason"] is None
    # unsuspending twice is a no-op
    assert (await client.post(f"/api/v1/ops/tenants/{company_id}/unsuspend")).status_code == 200

    assert (await client.get(f"/api/v1/public/companies/{tenant['slug']}")).status_code == 200
    assert (await client.get("/api/v1/applications", headers=bearer)).status_code == 200
    assert (await _login(client, tenant["email"])).status_code == 200

    # the tenant sees both events in its own feed, with no operator identity
    feed = (await client.get("/api/v1/activity")).json()
    events = [e for e in feed if e["type"].startswith("tenant.")]
    assert [e["type"] for e in events] == ["tenant.unsuspended", "tenant.suspended"]
    assert all(e["actor_email"] is None for e in events)
    assert events[1]["payload"] == {"reason": "Unpaid invoice"}


@db_required
@pytest.mark.usefixtures("migrated_db", "multi_mode")
async def test_export_returns_the_whole_tenant_and_tells_the_tenant(
    client: AsyncClient, db_session: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.models import Candidate

    tenant = await _register(client)
    company_id = (await client.get("/api/v1/auth/me")).json()["company_id"]
    job = await client.post(
        "/api/v1/jobs", json={"title": "Export Engineer", "description_md": "Ship it."}
    )
    assert job.status_code == 201, job.text
    candidate_email = f"cand-{uuid4().hex[:8]}@ganek-ci.dev"
    db_session.add(
        Candidate(company_id=UUID(company_id), email=candidate_email, name="Cara Export", links={})
    )
    await db_session.commit()
    tenant_cookies = dict(client.cookies)

    operator = await _register(client)
    monkeypatch.setattr(settings, "superadmin_user_ids", operator["id"])
    assert (await client.get(f"/api/v1/ops/tenants/{uuid4()}/export")).status_code == 404

    resp = await client.get(f"/api/v1/ops/tenants/{company_id}/export")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["tenant"]["id"] == company_id and body["tenant"]["slug"] == tenant["slug"]
    assert [u["email"] for u in body["users"]] == [tenant["email"]]
    assert body["users"][0]["role"] == "admin"
    assert [j["title"] for j in body["jobs"]] == ["Export Engineer"]
    assert body["jobs"][0]["description_md"] == "Ship it."
    # candidates in the DSAR bundle shape
    assert [c["candidate"]["email"] for c in body["candidates"]] == [candidate_email]
    assert body["candidates"][0]["candidate"]["name"] == "Cara Export"
    assert body["candidates"][0]["applications"] == []
    # no secrets and nothing from the operator's own workspace
    raw = resp.text
    for secret in ("password_hash", "totp_secret", "recovery_codes", "token_version"):
        assert secret not in raw
    assert operator["email"] not in raw

    # the tenant sees the export in its own feed, without the operator
    client.cookies.clear()
    client.cookies.update(tenant_cookies)
    feed = (await client.get("/api/v1/activity")).json()
    exported = [e for e in feed if e["type"] == "tenant.exported"]
    assert len(exported) == 1 and exported[0]["actor_email"] is None
