"""Operator plane (board card "Operator plane", first slice): the /ops gate
is a 404 for everyone off the allow-list, and a suspended tenant loses its
public pages, sign-in, sessions and API keys until it is unsuspended."""

from datetime import UTC, datetime, timedelta
from typing import Any, cast
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.core import plans
from app.core.config import settings
from app.core.ops import superadmin_ids
from app.core.plans import UNLIMITED, PlanLimits, PoweredBy
from app.core.tenancy import PUBLIC_UNAVAILABLE_DETAIL
from app.models import CompanyPlan
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
        ("PUT", f"/api/v1/ops/tenants/{company_id}/plan", {"plan_override": "team"}),
        ("DELETE", f"/api/v1/ops/tenants/{company_id}", {"confirm_slug": "x"}),
        ("POST", f"/api/v1/ops/tenants/{company_id}/impersonate", {}),
        ("DELETE", "/api/v1/ops/impersonation", None),
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


class _OverridePolicy:
    """Stand-in for the hosted policy (the core suite runs without ee/):
    Free allows 1 live job unless the billing row the company carries has
    an override. The real precedence is covered by ee/backend/tests; this
    proves the override reaches the policy on the tenant's next request."""

    name = "test_override"
    billing_enabled = False
    signup_plan = CompanyPlan.FREE

    def _plan(self, company: Any) -> CompanyPlan:
        account = company.billing_account
        if account is not None and account.plan_override is not None:
            return cast(CompanyPlan, account.plan_override)
        return cast(CompanyPlan, company.plan)

    def limits(self, company: Any) -> PlanLimits:
        return PlanLimits(max_live_jobs=1) if self._plan(company) is CompanyPlan.FREE else UNLIMITED

    def can_publish(self, company: Any, live_jobs: int) -> bool:
        limit = self.limits(company).max_live_jobs
        return limit is None or live_jobs < limit

    def upgrade_url(self, company: Any) -> None:
        return None

    def trial_ends_at(self, company: Any) -> None:
        return None

    def powered_by(self, company: Any) -> PoweredBy:
        return PoweredBy.NONE


async def _publish(client: AsyncClient, title: str) -> int:
    job = await client.post("/api/v1/jobs", json={"title": title})
    assert job.status_code == 201, job.text
    return (await client.post(f"/api/v1/jobs/{job.json()['id']}/publish")).status_code


@db_required
@pytest.mark.usefixtures("migrated_db", "multi_mode")
async def test_plan_override_lifts_limits_and_tells_the_tenant(
    client: AsyncClient, db_session: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.models import BillingAccount

    monkeypatch.setattr(settings, "quota_active_jobs", 0)
    monkeypatch.setattr(plans, "get_plan_policy", lambda: _OverridePolicy())
    await _register(client)
    company_id = (await client.get("/api/v1/auth/me")).json()["company_id"]
    assert await _publish(client, "First Role") == 200
    assert await _publish(client, "Second Role") == 402
    tenant_cookies = dict(client.cookies)

    operator = await _register(client)
    monkeypatch.setattr(settings, "superadmin_user_ids", operator["id"])
    url = f"/api/v1/ops/tenants/{company_id}/plan"
    assert (await client.put(url, json={"plan_override": "self_hosted"})).status_code == 422
    assert (
        await client.put(f"/api/v1/ops/tenants/{uuid4()}/plan", json={"plan_override": "team"})
    ).status_code == 404

    # clearing with no billing row is a no-op that writes nothing
    cleared = await client.put(url, json={"plan_override": None})
    assert cleared.status_code == 200 and cleared.json()["plan_override"] is None

    set_team = await client.put(url, json={"plan_override": "team"})
    assert set_team.status_code == 200, set_team.text
    assert set_team.json()["plan"] == "free" and set_team.json()["plan_override"] == "team"
    # the operator list shows the override column
    listed = (await client.get("/api/v1/ops/tenants")).json()
    row = next(t for t in listed if t["id"] == company_id)
    assert row["plan"] == "free" and row["plan_override"] == "team"
    assert row["trial_ends_at"] is None
    # setting the same value again records nothing
    assert (await client.put(url, json={"plan_override": "team"})).status_code == 200

    # the tenant's next publish follows the override at once
    operator_cookies = dict(client.cookies)
    client.cookies.clear()
    client.cookies.update(tenant_cookies)
    assert await _publish(client, "Third Role") == 200
    # the tenant cannot reach the route (the /ops gate answers 404)
    assert (await client.put(url, json={"plan_override": None})).status_code == 404

    # a running trial: the operator ends it and clears the override in one call
    account = await db_session.scalar(
        select(BillingAccount).where(BillingAccount.company_id == UUID(company_id))
    )
    account.trial_ends_at = datetime.now(UTC) + timedelta(days=10)
    await db_session.commit()
    client.cookies.clear()
    client.cookies.update(operator_cookies)
    ended = await client.put(url, json={"plan_override": None, "end_trial": True})
    assert ended.status_code == 200, ended.text
    assert ended.json()["plan_override"] is None
    trial_end = datetime.fromisoformat(ended.json()["trial_ends_at"])
    assert trial_end <= datetime.now(UTC)

    client.cookies.clear()
    client.cookies.update(tenant_cookies)
    assert await _publish(client, "Fourth Role") == 402
    feed = (await client.get("/api/v1/activity")).json()
    events = [e for e in feed if e["type"] == "tenant.plan_overridden"]
    assert [e["payload"] for e in events] == [
        {"plan": None, "previous": "team", "trial_ended": True},
        {"plan": "team", "previous": None, "trial_ended": False},
    ]
    assert all(e["actor_email"] is None for e in events)


def _jar(client: AsyncClient) -> dict[str, str]:
    return {name: value for name, value in client.cookies.items()}


@db_required
@pytest.mark.usefixtures("migrated_db", "multi_mode")
async def test_impersonation_reads_as_the_tenant_admin_and_tells_the_tenant(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.core.security import IMPERSONATION_COOKIE_NAME
    from app.core.tenancy import IMPERSONATION_READ_ONLY_DETAIL

    tenant = await _register(client)
    company_id = (await client.get("/api/v1/auth/me")).json()["company_id"]
    tenant_cookies = _jar(client)
    operator = await _register(client)
    monkeypatch.setattr(settings, "superadmin_user_ids", operator["id"])

    assert (
        await client.post(f"/api/v1/ops/tenants/{uuid4()}/impersonate", json={})
    ).status_code == 404
    unknown_user = await client.post(
        f"/api/v1/ops/tenants/{company_id}/impersonate", json={"user_id": str(uuid4())}
    )
    assert unknown_user.status_code == 404
    # a user of another tenant (the operator's own) cannot be picked through this tenant
    other = await client.post(
        f"/api/v1/ops/tenants/{company_id}/impersonate", json={"user_id": operator["id"]}
    )
    assert other.status_code == 404
    assert IMPERSONATION_COOKIE_NAME not in _jar(client)

    started = await client.post(f"/api/v1/ops/tenants/{company_id}/impersonate", json={})
    assert started.status_code == 200, started.text
    body = started.json()
    assert body["user_id"] == tenant["id"] and body["email"] == tenant["email"]
    expires_at = datetime.fromisoformat(body["expires_at"])
    remaining = expires_at - datetime.now(UTC)
    assert timedelta(minutes=59) < remaining <= timedelta(hours=1)
    assert IMPERSONATION_COOKIE_NAME in _jar(client)

    # the admin app now reads as the tenant admin, with the banner's end time
    me = await client.get("/api/v1/auth/me")
    assert me.status_code == 200
    assert me.json()["id"] == tenant["id"] and me.json()["company_id"] == company_id
    assert datetime.fromisoformat(me.json()["impersonation_expires_at"]) == expires_at
    assert (await client.get("/api/v1/company")).json()["slug"] == tenant["slug"]

    # reads only: a write in the tenant's name is refused and changes nothing
    job = await client.post("/api/v1/jobs", json={"title": "Sneaky", "description_md": "x"})
    assert job.status_code == 403 and job.json()["detail"] == IMPERSONATION_READ_ONLY_DETAIL
    jobs = await client.get("/api/v1/jobs")
    assert jobs.status_code == 200 and "Sneaky" not in jobs.text
    # the operator plane itself still answers to the operator's own session
    assert (await client.get("/api/v1/ops/tenants")).status_code == 200

    # ending it puts the operator back in their own account
    ended = await client.delete("/api/v1/ops/impersonation")
    assert ended.status_code == 204
    assert IMPERSONATION_COOKIE_NAME not in _jar(client)
    me = await client.get("/api/v1/auth/me")
    assert me.json()["id"] == operator["id"] and me.json()["impersonation_expires_at"] is None
    # ending twice is a no-op
    assert (await client.delete("/api/v1/ops/impersonation")).status_code == 204

    # the tenant sees both entries, as whom and until when, never the operator
    client.cookies.clear()
    client.cookies.update(tenant_cookies)
    feed = (await client.get("/api/v1/activity")).json()
    events = [e for e in feed if e["type"].startswith("tenant.impersonation")]
    assert [e["type"] for e in events] == [
        "tenant.impersonation_ended",
        "tenant.impersonation_started",
    ]
    assert all(e["actor_email"] is None for e in events)
    assert events[1]["payload"]["user"] == tenant["email"]
    assert datetime.fromisoformat(events[1]["payload"]["expires_at"]) == expires_at
    assert operator["email"] not in str(events)


@db_required
@pytest.mark.usefixtures("migrated_db", "multi_mode")
async def test_impersonation_cookie_is_useless_expired_or_off_the_allow_list(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    import itsdangerous.timed

    from app.core.security import IMPERSONATION_COOKIE_NAME, create_impersonation_token

    tenant = await _register(client)
    company_id = (await client.get("/api/v1/auth/me")).json()["company_id"]
    tenant_cookies = _jar(client)
    operator = await _register(client)
    monkeypatch.setattr(settings, "superadmin_user_ids", operator["id"])
    started = await client.post(f"/api/v1/ops/tenants/{company_id}/impersonate", json={})
    assert started.status_code == 200, started.text
    cookie = _jar(client)[IMPERSONATION_COOKIE_NAME]

    # the operator dropped from the allow-list: the cookie stops working at once
    monkeypatch.setattr(settings, "superadmin_user_ids", "")
    assert (await client.get("/api/v1/auth/me")).json()["id"] == operator["id"]
    monkeypatch.setattr(settings, "superadmin_user_ids", operator["id"])
    assert (await client.get("/api/v1/auth/me")).json()["id"] == tenant["id"]

    # the cookie on someone else's session (the tenant's own) does nothing
    client.cookies.clear()
    client.cookies.update(tenant_cookies)
    client.cookies.set(IMPERSONATION_COOKIE_NAME, cookie)
    assert (await client.get("/api/v1/auth/me")).json()["id"] == tenant["id"]
    job = await client.post("/api/v1/jobs", json={"title": "Own work", "description_md": "x"})
    assert job.status_code == 201, job.text  # not read-only: no impersonation applies

    # past one hour the signature expires and the operator is themselves again
    await _login(client, operator["email"])
    real_time = itsdangerous.timed.time.time
    monkeypatch.setattr(itsdangerous.timed.time, "time", lambda: real_time() - 3601)
    stale = create_impersonation_token(UUID(operator["id"]), 0, UUID(tenant["id"]), 0)
    monkeypatch.setattr(itsdangerous.timed.time, "time", real_time)
    client.cookies.set(IMPERSONATION_COOKIE_NAME, stale)
    me = (await client.get("/api/v1/auth/me")).json()
    assert me["id"] == operator["id"] and me["impersonation_expires_at"] is None

    # a suspended tenant cannot be impersonated
    assert (
        await client.post(f"/api/v1/ops/tenants/{company_id}/suspend", json={"reason": "x"})
    ).status_code == 200
    blocked = await client.post(f"/api/v1/ops/tenants/{company_id}/impersonate", json={})
    assert blocked.status_code == 409

    # signing out clears the impersonation cookie too
    await client.post(f"/api/v1/ops/tenants/{company_id}/unsuspend")
    client.cookies.clear()  # drop the hand-set cookies, keep only server-set ones
    await _login(client, operator["email"])
    assert (
        await client.post(f"/api/v1/ops/tenants/{company_id}/impersonate", json={})
    ).status_code == 200
    await client.post("/api/v1/auth/logout")
    assert IMPERSONATION_COOKIE_NAME not in _jar(client)
