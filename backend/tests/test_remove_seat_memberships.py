"""Removing a seat (card "SSO + multi-company user membership", slice 6):
an admin takes a person's seat in their company away while the account and
the person's other companies stay. A person who belongs only here is still
deactivated or anonymized instead."""

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
    User,
    UserRole,
)
from app.models.scorecard import Scorecard
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


async def _team(client: AsyncClient) -> dict[str, dict[str, Any]]:
    resp = await client.get("/api/v1/users")
    assert resp.status_code == 200, resp.text
    return {u["id"]: u for u in resp.json()}


async def _shared(
    client: AsyncClient, db: AsyncSession, role_in_b: UserRole = UserRole.MEMBER
) -> tuple[dict[str, Any], dict[str, Any]]:
    """A's admin (active in A) also holds a ``role_in_b`` seat in B. Ends
    signed in as B's admin."""
    a = await _register(client, "alpha")
    b = await _register(client, "beta")
    await _add_seat(db, a["id"], b["company_id"], role_in_b)
    await _login(client, b["email"])
    return a, b


async def _application(db: AsyncSession, company_id: str, job_id: str) -> Application:
    cand = Candidate(
        company_id=UUID(company_id), email=f"c-{uuid4().hex[:8]}@x.dev", name="Marta Vidal"
    )
    db.add(cand)
    await db.flush()
    row = Application(
        company_id=UUID(company_id),
        job_id=UUID(job_id),
        candidate_id=cand.id,
        cv_object_key=f"cvs/{uuid4().hex}.pdf",
        cv_filename="cv.pdf",
        cv_size=1,
    )
    db.add(row)
    await db.commit()
    return row


@pytest.mark.usefixtures("migrated_db", "multi_mode")
async def test_team_list_flags_a_person_with_seats_elsewhere(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    a, b = await _shared(client, db_session)
    team = await _team(client)
    assert team[a["id"]]["in_other_companies"] is True
    assert team[b["id"]]["in_other_companies"] is False


@pytest.mark.usefixtures("migrated_db", "multi_mode")
async def test_removing_a_seat_keeps_the_account_and_the_other_company(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    a, b = await _shared(client, db_session, UserRole.REVIEWER)
    resp = await client.delete(f"/api/v1/users/{a['id']}/membership")
    assert resp.status_code == 204, resp.text
    assert set(await _team(client)) == {b["id"]}
    assert await _seats(db_session, a["id"]) == {a["company_id"]}
    logged = (
        await db_session.execute(
            select(ActivityLog).where(
                ActivityLog.company_id == UUID(b["company_id"]),
                ActivityLog.type == "user.removed",
            )
        )
    ).scalar_one()
    assert logged.actor_user_id == UUID(b["id"])

    # gone from B: a second removal and a role edit are 404
    resp = await client.delete(f"/api/v1/users/{a['id']}/membership")
    assert resp.status_code == 404, resp.text
    resp = await client.patch(f"/api/v1/users/{a['id']}", json={"role": "member"})
    assert resp.status_code == 404, resp.text

    # A's admin still signs in to A as admin and cannot switch into B
    await _login(client, a["email"])
    me = (await client.get("/api/v1/auth/me")).json()
    assert me["company_id"] == a["company_id"]
    assert me["role"] == "admin"
    resp = await client.post("/api/v1/auth/switch-company", json={"company_id": b["company_id"]})
    assert resp.status_code == 404, resp.text


@pytest.mark.usefixtures("migrated_db", "multi_mode")
async def test_removing_the_active_seat_moves_the_session_to_another_company(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    a, b = await _shared(client, db_session, UserRole.MEMBER)
    # A's admin works in B right now
    await _login(client, a["email"])
    resp = await client.post("/api/v1/auth/switch-company", json={"company_id": b["company_id"]})
    assert resp.status_code == 200, resp.text
    a_session = dict(client.cookies)

    await _login(client, b["email"])
    resp = await client.delete(f"/api/v1/users/{a['id']}/membership")
    assert resp.status_code == 204, resp.text

    row = (await db_session.execute(select(User).where(User.id == UUID(a["id"])))).scalar_one()
    await db_session.refresh(row)
    assert str(row.company_id) == a["company_id"]
    assert row.role is UserRole.ADMIN
    assert await _seats(db_session, a["id"]) == {a["company_id"]}

    # the session they had open in B now reads A, never B
    client.cookies.clear()
    client.cookies.update(a_session)
    me = (await client.get("/api/v1/auth/me")).json()
    assert me["company_id"] == a["company_id"]
    assert set(await _team(client)) == {a["id"]}


@pytest.mark.usefixtures("migrated_db", "multi_mode")
async def test_a_person_who_belongs_only_here_is_not_removed_by_seat(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _register(client, "beta")
    resp = await client.post(
        "/api/v1/users",
        json={"email": f"m-{uuid4().hex[:8]}@ganek-ci.dev", "password": PASSWORD, "role": "member"},
    )
    assert resp.status_code == 201, resp.text
    member_id = resp.json()["id"]
    resp = await client.delete(f"/api/v1/users/{member_id}/membership")
    assert resp.status_code == 409, resp.text
    assert "belongs only to this company" in resp.json()["detail"]
    assert len(await _seats(db_session, member_id)) == 1


@pytest.mark.usefixtures("migrated_db", "multi_mode")
async def test_an_admin_cannot_remove_their_own_seat(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    a = await _register(client, "alpha")
    b = await _register(client, "beta")
    await _add_seat(db_session, b["id"], a["company_id"], UserRole.MEMBER)
    resp = await client.delete(f"/api/v1/users/{b['id']}/membership")
    assert resp.status_code == 409, resp.text
    assert "yourself" in resp.json()["detail"]
    assert await _seats(db_session, b["id"]) == {a["company_id"], b["company_id"]}


@pytest.mark.usefixtures("migrated_db", "multi_mode")
async def test_a_person_without_a_seat_here_is_not_found(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    a = await _register(client, "alpha")
    await _register(client, "beta")
    resp = await client.delete(f"/api/v1/users/{a['id']}/membership")
    assert resp.status_code == 404, resp.text
    assert await _seats(db_session, a["id"]) == {a["company_id"]}


@pytest.mark.usefixtures("migrated_db", "multi_mode")
async def test_a_non_admin_cannot_remove_a_seat(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    a, b = await _shared(client, db_session, UserRole.MEMBER)
    email = f"m-{uuid4().hex[:8]}@ganek-ci.dev"
    resp = await client.post(
        "/api/v1/users", json={"email": email, "password": PASSWORD, "role": "member"}
    )
    assert resp.status_code == 201, resp.text
    await _login(client, email)
    resp = await client.delete(f"/api/v1/users/{a['id']}/membership")
    assert resp.status_code == 403, resp.text
    assert await _seats(db_session, a["id"]) == {a["company_id"], b["company_id"]}


@pytest.mark.usefixtures("migrated_db", "multi_mode")
async def test_open_scorecards_here_are_dismissed_and_upcoming_interviews_block(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    a, b = await _shared(client, db_session, UserRole.REVIEWER)
    resp = await client.post(
        "/api/v1/jobs",
        json={"title": "Backend", "scorecard_template": [{"label": "Problem solving"}]},
    )
    assert resp.status_code == 201, resp.text
    job_id = resp.json()["id"]
    app_one = await _application(db_session, b["company_id"], job_id)
    resp = await client.post(
        f"/api/v1/scorecards/applications/{app_one.id}",
        json={"reviewer_user_id": a["id"]},
    )
    assert resp.status_code == 201, resp.text

    # an upcoming interview they conduct in B blocks the removal
    app_two = await _application(db_session, b["company_id"], job_id)
    interview = Interview(
        company_id=UUID(b["company_id"]),
        application_id=app_two.id,
        interviewer_user_id=UUID(a["id"]),
        duration_minutes=30,
        timezone="UTC",
        status=InterviewStatus.BOOKED,
        scheduled_start=datetime.now(UTC) + timedelta(days=2),
    )
    db_session.add(interview)
    await db_session.commit()
    resp = await client.delete(f"/api/v1/users/{a['id']}/membership")
    assert resp.status_code == 409, resp.text
    assert "upcoming interviews" in resp.json()["detail"]

    interview.status = InterviewStatus.CANCELLED
    await db_session.commit()
    resp = await client.delete(f"/api/v1/users/{a['id']}/membership")
    assert resp.status_code == 204, resp.text
    card = (
        await db_session.execute(select(Scorecard).where(Scorecard.application_id == app_one.id))
    ).scalar_one()
    await db_session.refresh(card)
    assert card.dismissed_at is not None
    assert card.dismissed_by_user_id == UUID(b["id"])
