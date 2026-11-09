"""Company switch and membership-backed tenancy (card "SSO + multi-company
user membership", slice 2): the active company of a session is one of the
user's memberships, the seat's role comes with it, and nothing of the other
company leaks while it is not the active one."""

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from tests.db import database_reachable

pytestmark = pytest.mark.skipif(
    not database_reachable(),
    reason="database required (start postgres or use CI)",
)

PASSWORD = "a-long-secure-password"


@pytest.fixture
def multi_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "mode", "multi")


def _job(title: str) -> dict[str, object]:
    return {
        "title": title,
        "description_md": "We build **things**.",
        "location": "Warsaw",
        "remote_policy": "hybrid",
        "employment_type": "full_time",
        "tags": ["python"],
    }


async def _register(client: AsyncClient, label: str) -> dict[str, Any]:
    """A fresh company with its admin signed in on ``client``, plus one job."""
    admin = {"email": f"{label}-{uuid4().hex[:8]}@ganek-ci.dev", "password": PASSWORD}
    resp = await client.post(
        "/api/v1/auth/register",
        json={"company_name": f"{label} Co {uuid4().hex[:6]}", **admin},
    )
    assert resp.status_code == 201, resp.text
    me = resp.json()
    job = await client.post("/api/v1/jobs", json=_job(f"{label} job"))
    assert job.status_code == 201, job.text
    return {**admin, "id": me["id"], "company_id": me["company_id"], "job_id": job.json()["id"]}


async def _login(client: AsyncClient, email: str) -> None:
    client.cookies.clear()
    resp = await client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
    assert resp.status_code == 200, resp.text


async def _add_seat(db: AsyncSession, user_id: str, company_id: str, role: str) -> None:
    from app.models import CompanyMembership, UserRole

    db.add(
        CompanyMembership(user_id=UUID(user_id), company_id=UUID(company_id), role=UserRole(role))
    )
    await db.commit()


async def _job_ids(client: AsyncClient) -> set[str]:
    resp = await client.get("/api/v1/jobs")
    assert resp.status_code == 200, resp.text
    return {j["id"] for j in resp.json()}


@pytest.mark.usefixtures("migrated_db", "multi_mode")
async def test_one_seat_lists_itself_and_switching_to_it_is_a_no_op(
    client: AsyncClient,
) -> None:
    a = await _register(client, "solo")
    seats = (await client.get("/api/v1/auth/companies")).json()
    assert [(s["company_id"], s["role"], s["active"]) for s in seats] == [
        (a["company_id"], "admin", True)
    ]
    resp = await client.post("/api/v1/auth/switch-company", json={"company_id": a["company_id"]})
    assert resp.status_code == 200, resp.text
    assert resp.json()["company_id"] == a["company_id"] and resp.json()["role"] == "admin"


@pytest.mark.usefixtures("migrated_db", "multi_mode")
async def test_switch_moves_tenancy_and_role_without_leaking_the_other_company(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    b = await _register(client, "beta")
    a = await _register(client, "alpha")
    # the alpha admin also holds a member seat in beta
    await _add_seat(db_session, a["id"], b["company_id"], "member")

    seats = (await client.get("/api/v1/auth/companies")).json()
    assert [(s["company_id"], s["role"], s["active"]) for s in seats] == [
        (a["company_id"], "admin", True),
        (b["company_id"], "member", False),
    ]

    # active alpha: alpha's job only, beta's job is a 404 like any foreign id
    assert a["job_id"] in await _job_ids(client)
    assert b["job_id"] not in await _job_ids(client)
    assert (await client.get(f"/api/v1/jobs/{b['job_id']}")).status_code == 404

    switched = await client.post(
        "/api/v1/auth/switch-company", json={"company_id": b["company_id"]}
    )
    assert switched.status_code == 200, switched.text
    assert switched.json()["company_id"] == b["company_id"]
    assert switched.json()["role"] == "member"
    me = (await client.get("/api/v1/auth/me")).json()
    assert (me["company_id"], me["role"]) == (b["company_id"], "member")

    # active beta: beta's job only, alpha's job gone, admin routes refused
    assert await _job_ids(client) == {b["job_id"]}
    assert (await client.get(f"/api/v1/jobs/{a['job_id']}")).status_code == 404
    assert (await client.get("/api/v1/api-keys")).status_code == 403
    users = (await client.get("/api/v1/users")).json()
    assert b["email"] in {u.get("email") for u in users}

    # the seats did not change: alpha stays admin, beta stays member
    from app.models import CompanyMembership

    db_session.expire_all()
    rows = (
        await db_session.execute(
            select(CompanyMembership.company_id, CompanyMembership.role).where(
                CompanyMembership.user_id == UUID(a["id"])
            )
        )
    ).all()
    assert sorted((str(c), r.value) for c, r in rows) == sorted(
        [(a["company_id"], "admin"), (b["company_id"], "member")]
    )

    # and back: the admin role in alpha returns with it
    back = await client.post("/api/v1/auth/switch-company", json={"company_id": a["company_id"]})
    assert back.status_code == 200 and back.json()["role"] == "admin"
    assert await _job_ids(client) == {a["job_id"]}
    assert (await client.get("/api/v1/api-keys")).status_code == 200


@pytest.mark.usefixtures("migrated_db", "multi_mode")
async def test_switch_to_a_company_without_a_seat_is_a_404_and_changes_nothing(
    client: AsyncClient,
) -> None:
    other = await _register(client, "other")
    a = await _register(client, "mine")
    for company_id in (other["company_id"], str(uuid4())):
        resp = await client.post("/api/v1/auth/switch-company", json={"company_id": company_id})
        assert resp.status_code == 404
        assert resp.json() == {"detail": "Company not found"}
    me = (await client.get("/api/v1/auth/me")).json()
    assert (me["company_id"], me["role"]) == (a["company_id"], "admin")
    assert await _job_ids(client) == {a["job_id"]}


@pytest.mark.usefixtures("migrated_db", "multi_mode")
async def test_switch_to_a_suspended_company_is_refused_with_the_reason(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    from app.models import Company

    b = await _register(client, "paused")
    a = await _register(client, "active")
    await _add_seat(db_session, a["id"], b["company_id"], "admin")
    company = await db_session.get(Company, UUID(b["company_id"]))
    assert company is not None
    company.suspended_at = datetime.now(UTC)
    company.suspension_reason = "Unpaid invoice"
    await db_session.commit()

    resp = await client.post("/api/v1/auth/switch-company", json={"company_id": b["company_id"]})
    assert resp.status_code == 403
    assert "Unpaid invoice" in resp.json()["detail"]
    assert (await client.get("/api/v1/auth/me")).json()["company_id"] == a["company_id"]


@pytest.mark.usefixtures("migrated_db", "multi_mode")
async def test_a_session_whose_active_seat_is_gone_is_signed_out(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    from app.models import CompanyMembership

    a = await _register(client, "seatless")
    assert (await client.get("/api/v1/auth/me")).status_code == 200
    await db_session.execute(
        delete(CompanyMembership).where(CompanyMembership.user_id == UUID(a["id"]))
    )
    await db_session.commit()
    assert (await client.get("/api/v1/auth/me")).status_code == 401
    assert (await client.get("/api/v1/jobs")).status_code == 401
    # the password still passes, but the session it hands out is refused too
    await _login(client, a["email"])
    assert (await client.get("/api/v1/auth/me")).status_code == 401
