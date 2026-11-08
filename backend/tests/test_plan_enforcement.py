"""Plan enforcement on publish (card B1b). The core suite runs without ee/,
so a stand-in policy with the BM3 limits plays the hosted one; the real
HostedPolicy is covered by ee/backend/tests."""

import uuid
from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import plans
from app.core.config import settings
from app.core.plans import UNLIMITED, PlanLimits
from app.models import Company, CompanyPlan
from tests.db import database_reachable

pytestmark = pytest.mark.skipif(
    not database_reachable(), reason="database not reachable (start postgres or use CI)"
)

PASSWORD = "a-long-secure-password"
UPGRADE = "https://billing.ganek-ci.dev/upgrade"
_LIMITS = {CompanyPlan.FREE: 1, CompanyPlan.STARTER: 5}


class _LimitedPolicy:
    name = "test_hosted"
    billing_enabled = True
    signup_plan = CompanyPlan.FREE

    def limits(self, company: Company) -> PlanLimits:
        limit = _LIMITS.get(company.plan)
        return UNLIMITED if limit is None else PlanLimits(max_live_jobs=limit)

    def can_publish(self, company: Company, live_jobs: int) -> bool:
        limit = self.limits(company).max_live_jobs
        return limit is None or live_jobs < limit

    def upgrade_url(self, company: Company) -> str | None:
        return UPGRADE


@pytest.fixture(autouse=True)
def _multi_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every test registers its own company; the abuse quota is off unless
    a test turns it on."""
    monkeypatch.setattr(settings, "mode", "multi")
    monkeypatch.setattr(settings, "quota_active_jobs", 0)


@pytest.fixture
def hosted(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(plans, "get_plan_policy", lambda: _LimitedPolicy())


async def _register(client: AsyncClient) -> str:
    resp = await client.post(
        "/api/v1/auth/register",
        json={
            "company_name": f"Plan Co {uuid4().hex[:6]}",
            "email": f"admin-{uuid4().hex[:8]}@ganek-ci.dev",
            "password": PASSWORD,
        },
    )
    assert resp.status_code == 201, resp.text
    return (await client.get("/api/v1/auth/me")).json()["company_id"]


async def _new_job(client: AsyncClient, title: str = "Backend Engineer") -> str:
    resp = await client.post("/api/v1/jobs", json={"title": title})
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def _set_plan(db: AsyncSession, company_id: str, plan: CompanyPlan) -> None:
    await db.execute(update(Company).where(Company.id == uuid.UUID(company_id)).values(plan=plan))
    await db.commit()


@pytest.mark.usefixtures("migrated_db", "hosted")
async def test_second_publish_on_free_is_402_with_upgrade_url(client: AsyncClient) -> None:
    await _register(client)
    first = await _new_job(client)
    assert (await client.post(f"/api/v1/jobs/{first}/publish")).status_code == 200
    second = await _new_job(client, "Second Role")
    resp = await client.post(f"/api/v1/jobs/{second}/publish")
    assert resp.status_code == 402
    detail = resp.json()["detail"]
    assert detail["code"] == "plan_limit"
    assert detail["limit"] == 1
    assert detail["upgrade_url"] == UPGRADE
    assert "allows 1 live job." in detail["message"]
    job = (await client.get(f"/api/v1/jobs/{second}")).json()
    assert job["status"] == "draft"


@pytest.mark.usefixtures("migrated_db", "hosted")
async def test_hosted_signup_starts_on_free(client: AsyncClient) -> None:
    await _register(client)
    plan = (await client.get("/api/v1/company/plan")).json()
    assert plan["plan"] == "free"
    assert plan["limits"] == {"max_live_jobs": 1}
    assert plan["billing_enabled"] is True
    assert plan["over_limit"] is False


@pytest.mark.usefixtures("migrated_db", "hosted")
async def test_plan_check_runs_before_the_abuse_quota(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "quota_active_jobs", 1)
    await _register(client)
    first = await _new_job(client)
    assert (await client.post(f"/api/v1/jobs/{first}/publish")).status_code == 200
    second = await _new_job(client, "Second Role")
    assert (await client.post(f"/api/v1/jobs/{second}/publish")).status_code == 402


@pytest.mark.usefixtures("migrated_db", "hosted")
async def test_downgrade_closes_nothing_and_blocks_publish_and_reopen(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    company_id = await _register(client)
    await _set_plan(db_session, company_id, CompanyPlan.TEAM)
    live = [await _new_job(client, f"Role {n}") for n in range(3)]
    for job_id in live:
        assert (await client.post(f"/api/v1/jobs/{job_id}/publish")).status_code == 200

    await _set_plan(db_session, company_id, CompanyPlan.FREE)
    plan = (await client.get("/api/v1/company/plan")).json()
    assert plan["live_jobs"] == 3
    assert plan["over_limit"] is True
    statuses = {job["id"]: job["status"] for job in (await client.get("/api/v1/jobs")).json()}
    assert all(statuses[job_id] == "published" for job_id in live)

    draft = await _new_job(client, "Draft Role")
    assert (await client.post(f"/api/v1/jobs/{draft}/publish")).status_code == 402
    assert (await client.post(f"/api/v1/jobs/{live[0]}/close")).status_code == 200
    reopen = await client.post(f"/api/v1/jobs/{live[0]}/publish")
    assert reopen.status_code == 402  # 2 still live, Free allows 1

    for job_id in live[1:]:
        assert (await client.post(f"/api/v1/jobs/{job_id}/close")).status_code == 200
    assert (await client.post(f"/api/v1/jobs/{live[0]}/publish")).status_code == 200
    plan = (await client.get("/api/v1/company/plan")).json()
    assert plan["live_jobs"] == 1
    assert plan["over_limit"] is False


@pytest.mark.usefixtures("migrated_db")
async def test_self_hosted_publishes_without_limit(client: AsyncClient) -> None:
    await _register(client)
    for n in range(3):
        job_id = await _new_job(client, f"Role {n}")
        assert (await client.post(f"/api/v1/jobs/{job_id}/publish")).status_code == 200
    plan = (await client.get("/api/v1/company/plan")).json()
    assert plan == {
        "plan": "self_hosted",
        "billing_enabled": False,
        "limits": {"max_live_jobs": None},
        "live_jobs": 3,
        "over_limit": False,
        "upgrade_url": None,
    }


@pytest.mark.usefixtures("migrated_db")
async def test_plan_needs_a_session(client: AsyncClient) -> None:
    assert (await client.get("/api/v1/company/plan")).status_code == 401
