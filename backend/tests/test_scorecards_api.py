"""Scorecard routes: request, submit, decline, dismiss, tenancy."""

from dataclasses import dataclass
from datetime import timedelta
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models import Application, Candidate, Job, Scorecard
from tests.db import database_reachable

pytestmark = pytest.mark.skipif(
    not database_reachable(), reason="database not reachable (start postgres or use CI)"
)

PW = "a-long-secure-password"


@pytest.fixture(autouse=True)
def multi_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "mode", "multi")


@dataclass
class Co:
    admin: dict[str, str]
    admin_id: str
    member: dict[str, str]
    member_id: str
    application_id: str
    criterion_id: str


async def _login(client: AsyncClient, creds: dict[str, str]) -> None:
    await client.post("/api/v1/auth/logout")
    resp = await client.post("/api/v1/auth/login", json=creds)
    assert resp.status_code == 200, resp.text


async def _company(client: AsyncClient, db: AsyncSession) -> Co:
    """Register a company (logged in as admin), add a member, seed one
    application on a job with a one-criterion template."""
    admin = {"email": f"admin-{uuid4().hex[:8]}@ganek-ci.dev", "password": PW}
    resp = await client.post(
        "/api/v1/auth/register", json={"company_name": f"Sc Co {uuid4().hex[:6]}", **admin}
    )
    assert resp.status_code == 201, resp.text
    admin_id = resp.json()["id"]
    member = {"email": f"member-{uuid4().hex[:8]}@ganek-ci.dev", "password": PW}
    resp = await client.post("/api/v1/users", json={**member, "role": "member"})
    assert resp.status_code == 201, resp.text
    member_id = resp.json()["id"]
    job_resp = await client.post(
        "/api/v1/jobs",
        json={"title": "Backend", "scorecard_template": [{"label": "Problem solving"}]},
    )
    assert job_resp.status_code == 201, job_resp.text
    job = await db.get(Job, job_resp.json()["id"])
    assert job is not None
    criterion_id = job.scorecard_template[0]["id"]
    candidate = Candidate(
        company_id=job.company_id, email=f"c-{uuid4().hex[:8]}@x.dev", name="Marta Vidal"
    )
    db.add(candidate)
    await db.flush()
    application = Application(
        company_id=job.company_id,
        job_id=job.id,
        candidate_id=candidate.id,
        cv_object_key=f"cvs/{uuid4().hex}.pdf",
        cv_filename="cv.pdf",
        cv_size=1,
    )
    db.add(application)
    await db.commit()
    return Co(admin, admin_id, member, member_id, str(application.id), criterion_id)


def _url(co: Co, suffix: str = "") -> str:
    return f"/api/v1/scorecards/applications/{co.application_id}{suffix}"


@pytest.mark.usefixtures("migrated_db")
async def test_request_list_submit_flow(client: AsyncClient, db_session: AsyncSession) -> None:
    co = await _company(client, db_session)
    resp = await client.post(_url(co), json={"reviewer_user_id": co.member_id})
    assert resp.status_code == 201, resp.text
    assert resp.json()["state"] == "open"
    assert resp.json()["criteria"][0]["id"] == co.criterion_id

    await _login(client, co.member)
    mine = (await client.get("/api/v1/scorecards/mine")).json()
    assert len(mine) == 1
    assert mine[0]["candidate_name"] == "Marta Vidal"
    assert mine[0]["job_title"] == "Backend"
    assert f"selected={co.application_id}" in mine[0]["href"]

    body = {
        "ratings": {co.criterion_id: 3},
        "recommendation": "yes",
        "comment": "Solid",
    }
    resp = await client.put(_url(co, "/mine"), json=body)
    assert resp.status_code == 200, resp.text
    assert resp.json()["state"] == "submitted"
    assert resp.json()["can_edit"] is True
    assert resp.json()["edited"] is False
    assert (await client.get("/api/v1/scorecards/mine")).json() == []
    assert len((await client.get("/api/v1/scorecards/mine?state=all")).json()) == 1

    await _login(client, co.admin)
    listed = (await client.get(_url(co))).json()
    assert len(listed) == 1
    assert listed[0]["recommendation"] == "yes"
    assert listed[0]["ratings"] == {co.criterion_id: 3}
    assert listed[0]["can_edit"] is False

    # an hour later (still inside the 24h edit window)
    row = (
        await db_session.execute(
            select(Scorecard).where(Scorecard.application_id == UUID(co.application_id))
        )
    ).scalar_one()
    row.submitted_at = row.submitted_at - timedelta(hours=1)
    await db_session.commit()

    await _login(client, co.member)
    resp = await client.put(_url(co, "/mine"), json={**body, "recommendation": "no"})
    assert resp.status_code == 200, resp.text
    assert resp.json()["edited"] is True
    assert resp.json()["recommendation"] == "no"


@pytest.mark.usefixtures("migrated_db")
async def test_request_404_other_company_reviewer(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    other = await _company(client, db_session)
    co = await _company(client, db_session)
    resp = await client.post(_url(co), json={"reviewer_user_id": other.member_id})
    assert resp.status_code == 404
    resp = await client.post(_url(co), json={"reviewer_user_id": str(uuid4())})
    assert resp.status_code == 404


@pytest.mark.usefixtures("migrated_db")
async def test_request_404_inactive_reviewer(client: AsyncClient, db_session: AsyncSession) -> None:
    co = await _company(client, db_session)
    resp = await client.patch(f"/api/v1/users/{co.member_id}", json={"is_active": False})
    assert resp.status_code == 200, resp.text
    resp = await client.post(_url(co), json={"reviewer_user_id": co.member_id})
    assert resp.status_code == 404


@pytest.mark.usefixtures("migrated_db")
async def test_request_409_open(client: AsyncClient, db_session: AsyncSession) -> None:
    co = await _company(client, db_session)
    assert (await client.post(_url(co), json={"reviewer_user_id": co.member_id})).status_code == 201
    resp = await client.post(_url(co), json={"reviewer_user_id": co.member_id})
    assert resp.status_code == 409


@pytest.mark.usefixtures("migrated_db")
async def test_request_409_self(client: AsyncClient, db_session: AsyncSession) -> None:
    co = await _company(client, db_session)
    resp = await client.post(_url(co), json={"reviewer_user_id": co.admin_id})
    assert resp.status_code == 409


@pytest.mark.usefixtures("migrated_db")
async def test_submit_422_bad_rating_id(client: AsyncClient, db_session: AsyncSession) -> None:
    co = await _company(client, db_session)
    await client.post(_url(co), json={"reviewer_user_id": co.member_id})
    await _login(client, co.member)
    resp = await client.put(
        _url(co, "/mine"), json={"ratings": {"nope": 2}, "recommendation": "yes"}
    )
    assert resp.status_code == 422
    # nothing was stored
    assert (await client.get("/api/v1/scorecards/mine")).json()[0]["state"] == "open"


@pytest.mark.usefixtures("migrated_db")
async def test_submit_404_without_row(client: AsyncClient, db_session: AsyncSession) -> None:
    co = await _company(client, db_session)
    await _login(client, co.member)
    resp = await client.put(_url(co, "/mine"), json={"recommendation": "yes"})
    assert resp.status_code == 404
    assert (await client.post(_url(co, "/mine/decline"))).status_code == 404


@pytest.mark.usefixtures("migrated_db")
async def test_admin_cannot_submit_for_reviewer(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    co = await _company(client, db_session)
    await client.post(_url(co), json={"reviewer_user_id": co.member_id})
    # the admin has no row of their own: the member's row is out of reach
    resp = await client.put(_url(co, "/mine"), json={"recommendation": "yes"})
    assert resp.status_code == 404
    assert (await client.get(_url(co))).json()[0]["state"] == "open"


@pytest.mark.usefixtures("migrated_db")
async def test_decline_then_mine_open_is_empty(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    co = await _company(client, db_session)
    await client.post(_url(co), json={"reviewer_user_id": co.member_id})
    await _login(client, co.member)
    assert (await client.post(_url(co, "/mine/decline"))).status_code == 204
    assert (await client.get("/api/v1/scorecards/mine")).json() == []
    assert (await client.post(_url(co, "/mine/decline"))).status_code == 409
    resp = await client.put(_url(co, "/mine"), json={"recommendation": "yes"})
    assert resp.status_code == 409
    await _login(client, co.admin)
    assert (await client.get(_url(co))).json()[0]["state"] == "declined"


@pytest.mark.usefixtures("migrated_db")
async def test_dismiss_204_then_409(client: AsyncClient, db_session: AsyncSession) -> None:
    co = await _company(client, db_session)
    sc = (await client.post(_url(co), json={"reviewer_user_id": co.member_id})).json()
    assert (await client.post(f"/api/v1/scorecards/{sc['id']}/dismiss")).status_code == 204
    assert (await client.post(f"/api/v1/scorecards/{sc['id']}/dismiss")).status_code == 409
    assert (await client.get(_url(co))).json()[0]["state"] == "dismissed"


@pytest.mark.usefixtures("migrated_db")
async def test_dismiss_404_other_company(client: AsyncClient, db_session: AsyncSession) -> None:
    co = await _company(client, db_session)
    sc = (await client.post(_url(co), json={"reviewer_user_id": co.member_id})).json()
    await _company(client, db_session)  # logs in as another company's admin
    assert (await client.post(f"/api/v1/scorecards/{sc['id']}/dismiss")).status_code == 404
    await _login(client, co.admin)
    assert (await client.get(_url(co))).json()[0]["state"] == "open"


@pytest.mark.usefixtures("migrated_db")
async def test_other_company_cannot_read_list(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    co = await _company(client, db_session)
    await client.post(_url(co), json={"reviewer_user_id": co.member_id})
    await _company(client, db_session)
    assert (await client.get(_url(co))).status_code == 404
    assert (await client.post(_url(co), json={"reviewer_user_id": co.member_id})).status_code == 404
