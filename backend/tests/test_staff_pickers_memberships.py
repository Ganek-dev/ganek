"""Interviewer, reviewer and job owner pickers over memberships (card "SSO +
multi-company user membership", slice 5): anyone with an active seat in the
company can be picked, whichever company is active for them, and the mail
links follow the role of the seat in THAT company."""

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models import Application, Candidate, CompanyMembership, User, UserRole
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


async def _application(client: AsyncClient, db: AsyncSession, company_id: str) -> str:
    """A job in the signed-in company with one seeded application (no CV upload)."""
    resp = await client.post(
        "/api/v1/jobs",
        json={"title": "Backend", "scorecard_template": [{"label": "Problem solving"}]},
    )
    assert resp.status_code == 201, resp.text
    job_id = UUID(resp.json()["id"])
    cand = Candidate(
        company_id=UUID(company_id), email=f"c-{uuid4().hex[:8]}@x.dev", name="Marta Vidal"
    )
    db.add(cand)
    await db.flush()
    app_row = Application(
        company_id=UUID(company_id),
        job_id=job_id,
        candidate_id=cand.id,
        cv_object_key=f"cvs/{uuid4().hex}.pdf",
        cv_filename="cv.pdf",
        cv_size=1,
    )
    db.add(app_row)
    await db.commit()
    return str(app_row.id)


async def _shared(
    client: AsyncClient, db: AsyncSession, role_in_b: UserRole
) -> tuple[dict[str, Any], dict[str, Any], str]:
    """A's admin (active in A) also holds a ``role_in_b`` seat in B; B has an
    application. Ends signed in as B's admin."""
    a = await _register(client, "alpha")
    b = await _register(client, "beta")
    await _add_seat(db, a["id"], b["company_id"], role_in_b)
    application_id = await _application(client, db, b["company_id"])
    return a, b, application_id


@pytest.mark.usefixtures("migrated_db", "multi_mode")
async def test_interviewer_with_a_seat_here_can_be_picked(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    a, _b, application_id = await _shared(client, db_session, UserRole.MEMBER)
    resp = await client.post(
        f"/api/v1/applications/{application_id}/interview/slot-preview",
        json={"interviewer_user_id": a["id"], "duration_minutes": 45, "timezone": "UTC"},
    )
    assert resp.status_code == 200, resp.text


@pytest.mark.usefixtures("migrated_db", "multi_mode")
async def test_interviewer_without_a_seat_here_is_not_found(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    a = await _register(client, "alpha")
    b = await _register(client, "beta")
    application_id = await _application(client, db_session, b["company_id"])
    resp = await client.post(
        f"/api/v1/applications/{application_id}/interview/slot-preview",
        json={"interviewer_user_id": a["id"], "duration_minutes": 45, "timezone": "UTC"},
    )
    assert resp.status_code == 404, resp.text


@pytest.mark.usefixtures("migrated_db", "multi_mode")
async def test_inactive_seat_holder_is_not_pickable(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    a, _b, application_id = await _shared(client, db_session, UserRole.MEMBER)
    row = (await db_session.execute(select(User).where(User.id == UUID(a["id"])))).scalar_one()
    row.is_active = False
    await db_session.commit()
    resp = await client.post(
        f"/api/v1/applications/{application_id}/interview/slot-preview",
        json={"interviewer_user_id": a["id"], "duration_minutes": 45, "timezone": "UTC"},
    )
    assert resp.status_code == 404, resp.text
    resp = await client.post(
        f"/api/v1/scorecards/applications/{application_id}",
        json={"reviewer_user_id": a["id"]},
    )
    assert resp.status_code == 404, resp.text


@pytest.mark.usefixtures("migrated_db", "multi_mode")
async def test_reviewer_seat_gets_the_review_link_and_lands_in_mine(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.services import outbox as outbox_service

    queued: list[dict[str, Any]] = []
    real = outbox_service.queue_email

    async def spy(db: AsyncSession, **kw: Any) -> Any:
        queued.append(kw)
        return await real(db, **kw)

    monkeypatch.setattr(outbox_service, "queue_email", spy)
    # A's admin is an ADMIN in A (active) but only a REVIEWER in B
    a, b, application_id = await _shared(client, db_session, UserRole.REVIEWER)
    resp = await client.post(
        f"/api/v1/scorecards/applications/{application_id}",
        json={"reviewer_user_id": a["id"]},
    )
    assert resp.status_code == 201, resp.text
    mail = next(m for m in queued if m["kind"] == "scorecard_request")
    assert mail["to"] == a["email"]
    assert "/review/" in str(mail["url"]), mail["url"]

    # after switching into B, the request is theirs
    await _login(client, a["email"])
    resp = await client.post("/api/v1/auth/switch-company", json={"company_id": b["company_id"]})
    assert resp.status_code == 200, resp.text
    mine = (await client.get("/api/v1/scorecards/mine")).json()
    assert [m["application_id"] for m in mine] == [application_id]


@pytest.mark.usefixtures("migrated_db", "multi_mode")
async def test_job_owner_can_be_a_seat_holder_from_elsewhere(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    a, _b, _application_id = await _shared(client, db_session, UserRole.MEMBER)
    resp = await client.post("/api/v1/jobs", json={"title": "Owned", "owner_user_id": a["id"]})
    assert resp.status_code == 201, resp.text
    assert resp.json()["owner_user_id"] == a["id"]

    stranger = await _register(client, "gamma")
    await _login(client, _b["email"])
    resp = await client.post(
        "/api/v1/jobs", json={"title": "Not owned", "owner_user_id": stranger["id"]}
    )
    assert resp.status_code == 422, resp.text


@pytest.mark.usefixtures("migrated_db", "multi_mode")
async def test_reminder_reaches_a_seat_holder_whose_active_company_is_elsewhere(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    from app.services import scorecards as svc

    a, b, application_id = await _shared(client, db_session, UserRole.MEMBER)
    resp = await client.post(
        f"/api/v1/scorecards/applications/{application_id}",
        json={"reviewer_user_id": a["id"]},
    )
    assert resp.status_code == 201, resp.text
    row = (
        await db_session.execute(select(Scorecard).where(Scorecard.id == UUID(resp.json()["id"])))
    ).scalar_one()
    row.due_from = datetime.now(UTC) - timedelta(days=10)
    await db_session.commit()
    due = await svc.due_for_reminder(db_session, now=datetime.now(UTC))
    assert row.id in {r.id for r in due}

    # once the seat in B is gone, B stops reminding them
    seat = (
        await db_session.execute(
            select(CompanyMembership).where(
                CompanyMembership.user_id == UUID(a["id"]),
                CompanyMembership.company_id == UUID(b["company_id"]),
            )
        )
    ).scalar_one()
    await db_session.delete(seat)
    await db_session.commit()
    due = await svc.due_for_reminder(db_session, now=datetime.now(UTC))
    assert row.id not in {r.id for r in due}
