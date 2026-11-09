"""Leaving a company yourself (card "SSO + multi-company user membership",
slice 8): the signed-in person gives up their own seat in one company while
their account and their other companies stay. The rules an admin meets when
removing a seat apply: at least one company stays, a company keeps an
active admin, upcoming interviews there are handed over first."""

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models import (
    ActivityLog,
    Application,
    Candidate,
    CompanyMembership,
    Interview,
    InterviewStatus,
    UserRole,
)
from tests.db import database_reachable

pytestmark = pytest.mark.skipif(
    not database_reachable(),
    reason="database required (start postgres or use CI)",
)

PASSWORD = "a-long-secure-password"


@pytest.fixture
def multi_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "mode", "multi")


async def _register(client: AsyncClient, label: str) -> dict[str, Any]:
    admin = {"email": f"{label}-{uuid4().hex[:8]}@ganek-ci.dev", "password": PASSWORD}
    resp = await client.post(
        "/api/v1/auth/register",
        json={"company_name": f"{label} Co {uuid4().hex[:6]}", **admin},
    )
    assert resp.status_code == 201, resp.text
    me = resp.json()
    return {**admin, "id": me["id"], "company_id": me["company_id"]}


async def _login(client: AsyncClient, email: str) -> None:
    client.cookies.clear()
    resp = await client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
    assert resp.status_code == 200, resp.text


async def _add_seat(db: AsyncSession, user_id: str, company_id: str, role: UserRole) -> None:
    db.add(CompanyMembership(user_id=UUID(user_id), company_id=UUID(company_id), role=role))
    await db.commit()


async def _seats(db: AsyncSession, user_id: str) -> set[str]:
    rows = await db.execute(
        select(CompanyMembership.company_id).where(CompanyMembership.user_id == UUID(user_id))
    )
    return {str(c) for c in rows.scalars().all()}


async def _shared(
    client: AsyncClient, db: AsyncSession, role_in_b: UserRole = UserRole.MEMBER
) -> tuple[dict[str, Any], dict[str, Any]]:
    """A's admin also holds a ``role_in_b`` seat in B. Ends signed in as A's
    admin, active in A."""
    a = await _register(client, "alpha")
    b = await _register(client, "beta")
    await _add_seat(db, a["id"], b["company_id"], role_in_b)
    await _login(client, a["email"])
    return a, b


@pytest.mark.usefixtures("migrated_db", "multi_mode")
async def test_leaving_another_company_keeps_the_active_one(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    a, b = await _shared(client, db_session, UserRole.REVIEWER)
    resp = await client.delete(f"/api/v1/auth/companies/{b['company_id']}")
    assert resp.status_code == 200, resp.text
    me = resp.json()
    assert me["company_id"] == a["company_id"]
    assert me["role"] == "admin"
    assert await _seats(db_session, a["id"]) == {a["company_id"]}
    companies = (await client.get("/api/v1/auth/companies")).json()
    assert [c["company_id"] for c in companies] == [a["company_id"]]

    logged = (
        await db_session.execute(
            select(ActivityLog).where(
                ActivityLog.company_id == UUID(b["company_id"]),
                ActivityLog.type == "user.left",
            )
        )
    ).scalar_one()
    assert logged.actor_user_id == UUID(a["id"])

    # B's team no longer lists them
    await _login(client, b["email"])
    team = (await client.get("/api/v1/users")).json()
    assert {u["id"] for u in team} == {b["id"]}


@pytest.mark.usefixtures("migrated_db", "multi_mode")
async def test_leaving_the_active_company_moves_to_another_seat(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    a, b = await _shared(client, db_session, UserRole.MEMBER)
    resp = await client.post("/api/v1/auth/switch-company", json={"company_id": b["company_id"]})
    assert resp.status_code == 200, resp.text
    assert resp.json()["role"] == "member"

    resp = await client.delete(f"/api/v1/auth/companies/{b['company_id']}")
    assert resp.status_code == 200, resp.text
    assert resp.json()["company_id"] == a["company_id"]
    assert resp.json()["role"] == "admin"
    # the same session now reads A
    me = (await client.get("/api/v1/auth/me")).json()
    assert me["company_id"] == a["company_id"]
    team = (await client.get("/api/v1/users")).json()
    assert {u["id"] for u in team} == {a["id"]}


@pytest.mark.usefixtures("migrated_db", "multi_mode")
async def test_the_only_company_cannot_be_left(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    a = await _register(client, "alpha")
    resp = await client.delete(f"/api/v1/auth/companies/{a['company_id']}")
    assert resp.status_code == 409, resp.text
    assert "only company" in resp.json()["detail"]
    assert await _seats(db_session, a["id"]) == {a["company_id"]}


@pytest.mark.usefixtures("migrated_db", "multi_mode")
async def test_the_last_admin_cannot_leave(client: AsyncClient, db_session: AsyncSession) -> None:
    a, b = await _shared(client, db_session, UserRole.MEMBER)
    # A's admin is A's only admin: leaving A is refused, leaving B is fine
    resp = await client.delete(f"/api/v1/auth/companies/{a['company_id']}")
    assert resp.status_code == 409, resp.text
    assert "last admin" in resp.json()["detail"]
    assert await _seats(db_session, a["id"]) == {a["company_id"], b["company_id"]}

    # with a second admin in A they may go, and land in B as a member
    resp = await client.post(
        "/api/v1/users",
        json={"email": f"m-{uuid4().hex[:8]}@ganek-ci.dev", "password": PASSWORD, "role": "admin"},
    )
    assert resp.status_code == 201, resp.text
    resp = await client.delete(f"/api/v1/auth/companies/{a['company_id']}")
    assert resp.status_code == 200, resp.text
    assert resp.json()["company_id"] == b["company_id"]
    assert resp.json()["role"] == "member"
    assert await _seats(db_session, a["id"]) == {b["company_id"]}


@pytest.mark.usefixtures("migrated_db", "multi_mode")
async def test_a_company_without_a_seat_is_not_found(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    a, _b = await _shared(client, db_session)
    c = await _register(client, "gamma")
    await _login(client, a["email"])
    for target in (c["company_id"], str(uuid4())):
        resp = await client.delete(f"/api/v1/auth/companies/{target}")
        assert resp.status_code == 404, resp.text
        assert resp.json()["detail"] == "Company not found"
    assert len(await _seats(db_session, a["id"])) == 2


@pytest.mark.usefixtures("migrated_db", "multi_mode")
async def test_signed_out_cannot_leave(client: AsyncClient, db_session: AsyncSession) -> None:
    a, b = await _shared(client, db_session)
    client.cookies.clear()
    resp = await client.delete(f"/api/v1/auth/companies/{b['company_id']}")
    assert resp.status_code == 401, resp.text
    assert len(await _seats(db_session, a["id"])) == 2


@pytest.mark.usefixtures("migrated_db", "multi_mode")
async def test_upcoming_interviews_there_block_leaving(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    a, b = await _shared(client, db_session, UserRole.MEMBER)
    await _login(client, b["email"])
    resp = await client.post("/api/v1/jobs", json={"title": "Backend"})
    assert resp.status_code == 201, resp.text
    cand = Candidate(
        company_id=UUID(b["company_id"]), email=f"c-{uuid4().hex[:8]}@x.dev", name="Marta Vidal"
    )
    db_session.add(cand)
    await db_session.flush()
    application = Application(
        company_id=UUID(b["company_id"]),
        job_id=UUID(resp.json()["id"]),
        candidate_id=cand.id,
        cv_object_key=f"cvs/{uuid4().hex}.pdf",
        cv_filename="cv.pdf",
        cv_size=1,
    )
    db_session.add(application)
    await db_session.flush()
    interview = Interview(
        company_id=UUID(b["company_id"]),
        application_id=application.id,
        interviewer_user_id=UUID(a["id"]),
        duration_minutes=30,
        timezone="UTC",
        status=InterviewStatus.BOOKED,
        scheduled_start=datetime.now(UTC) + timedelta(days=2),
    )
    db_session.add(interview)
    await db_session.commit()

    await _login(client, a["email"])
    resp = await client.delete(f"/api/v1/auth/companies/{b['company_id']}")
    assert resp.status_code == 409, resp.text
    assert "upcoming interviews" in resp.json()["detail"]
    assert len(await _seats(db_session, a["id"])) == 2

    interview.status = InterviewStatus.CANCELLED
    await db_session.commit()
    resp = await client.delete(f"/api/v1/auth/companies/{b['company_id']}")
    assert resp.status_code == 200, resp.text
    assert await _seats(db_session, a["id"]) == {a["company_id"]}
