"""Multi-round interviews: one active interview per round, the next round
opens once the latest is over, the status page lists the rounds in order."""

import uuid
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.security import create_status_token
from app.models import Interview, InterviewStatus
from tests.db import database_reachable, s3_reachable
from tests.helpers import upload_pdf

pytestmark = pytest.mark.skipif(
    not (database_reachable() and s3_reachable()),
    reason="database and object storage required (start postgres+minio or use CI)",
)


@pytest.fixture
def multi_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "mode", "multi")


@pytest.fixture
def captured(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, object]]:
    from app.services import email as email_service

    invites: list[dict[str, object]] = []
    monkeypatch.setattr(email_service, "send_interview_invite", lambda **kw: invites.append(kw))
    for name in (
        "send_interview_confirmed",
        "send_interview_scheduled",
        "send_interview_cancelled",
        "send_interview_cancelled_interviewer",
    ):
        monkeypatch.setattr(email_service, name, lambda **kw: None)
    return invites


async def _company_with_applicant(client: AsyncClient) -> tuple[str, str]:
    """Register, publish, apply; returns (application_id, admin_user_id), logged in as admin."""
    creds = {
        "email": f"admin-{uuid4().hex[:8]}@ganek-ci.dev",
        "password": "a-long-secure-password",
    }
    name = f"Rounds Co {uuid4().hex[:6]}"
    resp = await client.post("/api/v1/auth/register", json={"company_name": name, **creds})
    assert resp.status_code == 201, resp.text
    admin_user_id = resp.json()["id"]
    slug = name.lower().replace(" ", "-")
    job = (await client.post("/api/v1/jobs", json={"title": "Backend Engineer"})).json()
    assert (await client.post(f"/api/v1/jobs/{job['id']}/publish")).status_code == 200
    await client.post("/api/v1/auth/logout")
    base = f"/api/v1/public/companies/{slug}/jobs/{job['slug']}"
    ticket = (await client.post(f"{base}/apply/upload-url")).json()
    assert (await upload_pdf(ticket, b"%PDF-1.4 rounds")).is_success
    resp = await client.post(
        f"{base}/apply",
        json={
            "name": "Marta Vidal",
            "email": f"cand-{uuid4().hex[:8]}@ganek-ci.dev",
            "cv_object_key": ticket["object_key"],
            "cv_filename": "marta.pdf",
        },
    )
    assert resp.status_code == 201, resp.text
    assert (await client.post("/api/v1/auth/login", json=creds)).status_code == 200
    application_id = (await client.get("/api/v1/applications")).json()["items"][0]["id"]
    return application_id, admin_user_id


def _payload(admin_id: str) -> dict[str, object]:
    return {"interviewer_user_id": admin_id, "duration_minutes": 30, "timezone": "Europe/Berlin"}


async def _finish(db_session: AsyncSession, interview_id: str) -> None:
    """Mark a round as booked in the past: the interview is over."""
    row = (
        await db_session.execute(select(Interview).where(Interview.id == uuid.UUID(interview_id)))
    ).scalar_one()
    row.status = InterviewStatus.BOOKED
    row.scheduled_start = datetime.now(UTC) - timedelta(hours=3)
    await db_session.commit()


@pytest.mark.usefixtures("migrated_db", "bucket", "multi_mode")
async def test_next_round_opens_once_the_previous_is_over(
    client: AsyncClient, db_session: AsyncSession, captured: list[dict[str, object]]
) -> None:
    application_id, admin_id = await _company_with_applicant(client)
    url = f"/api/v1/applications/{application_id}/interview"
    first = await client.post(url, json=_payload(admin_id))
    assert first.status_code == 201, first.text
    assert first.json()["round_number"] == 1
    assert first.json()["completed"] is False
    # round 1 still pending: no second request
    assert (await client.post(url, json=_payload(admin_id))).status_code == 409

    await _finish(db_session, first.json()["id"])
    assert (await client.get(url)).json() is None  # a finished round is not active
    second = await client.post(url, json=_payload(admin_id))
    assert second.status_code == 201, second.text
    assert second.json()["round_number"] == 2
    assert (await client.get(url)).json()["id"] == second.json()["id"]
    assert len(captured) == 2  # each round mails its own booking link

    rounds = (await client.get(f"/api/v1/applications/{application_id}/interviews")).json()
    assert [(r["round_number"], r["status"], r["completed"]) for r in rounds] == [
        (1, "booked", True),
        (2, "pending", False),
    ]


@pytest.mark.usefixtures("migrated_db", "bucket", "multi_mode")
async def test_upcoming_booked_round_blocks_the_next(
    client: AsyncClient, captured: list[dict[str, object]]
) -> None:
    application_id, admin_id = await _company_with_applicant(client)
    url = f"/api/v1/applications/{application_id}/interview"
    assert (await client.post(url, json=_payload(admin_id))).status_code == 201
    token = str(captured[0]["booking_url"]).rsplit("/", 1)[-1]
    slots = (await client.get(f"/api/v1/public/interviews/{token}")).json()["available_slots"]
    booked = await client.post(f"/api/v1/public/interviews/{token}/book", json={"start": slots[0]})
    assert booked.status_code == 200, booked.text
    resp = await client.post(url, json=_payload(admin_id))
    assert resp.status_code == 409
    assert "current round" in resp.json()["detail"]


@pytest.mark.usefixtures("migrated_db", "bucket", "multi_mode")
async def test_cancelled_round_is_reused_and_round_two_books(
    client: AsyncClient, db_session: AsyncSession, captured: list[dict[str, object]]
) -> None:
    application_id, admin_id = await _company_with_applicant(client)
    url = f"/api/v1/applications/{application_id}/interview"
    first = (await client.post(url, json=_payload(admin_id))).json()
    await _finish(db_session, first["id"])
    assert (await client.post(url, json=_payload(admin_id))).json()["round_number"] == 2
    assert (await client.post(f"{url}/cancel")).status_code == 200
    again = await client.post(url, json=_payload(admin_id))
    assert again.status_code == 201
    assert again.json()["round_number"] == 2  # the cancelled request freed round 2

    # round 2 books through its own token like round 1 did
    token = str(captured[-1]["booking_url"]).rsplit("/", 1)[-1]
    slots = (await client.get(f"/api/v1/public/interviews/{token}")).json()["available_slots"]
    booked = await client.post(f"/api/v1/public/interviews/{token}/book", json={"start": slots[0]})
    assert booked.status_code == 200, booked.text
    assert (await client.get(url)).json()["status"] == "booked"

    rounds = (await client.get(f"/api/v1/applications/{application_id}/interviews")).json()
    assert [(r["round_number"], r["status"]) for r in rounds] == [
        (1, "booked"),
        (2, "cancelled"),
        (2, "booked"),
    ]


@pytest.mark.usefixtures("migrated_db", "bucket", "multi_mode")
async def test_status_page_lists_rounds_in_order(
    client: AsyncClient, db_session: AsyncSession, captured: list[dict[str, object]]
) -> None:
    application_id, admin_id = await _company_with_applicant(client)
    url = f"/api/v1/applications/{application_id}/interview"
    first = (await client.post(url, json=_payload(admin_id))).json()
    await _finish(db_session, first["id"])
    assert (await client.post(url, json=_payload(admin_id))).status_code == 201

    token = create_status_token(uuid.UUID(application_id))
    status = (await client.get(f"/api/v1/public/applications/{token}")).json()
    assert [(r["round_number"], r["status"], r["completed"]) for r in status["interviews"]] == [
        (1, "booked", True),
        (2, "pending", False),
    ]
    assert "interviewer_email" not in status["interviews"][0]


@pytest.mark.usefixtures("migrated_db", "bucket", "multi_mode")
async def test_round_index_allows_one_active_row_per_round(
    client: AsyncClient, db_session: AsyncSession, captured: list[dict[str, object]]
) -> None:
    application_id, admin_id = await _company_with_applicant(client)
    first = (
        await client.post(
            f"/api/v1/applications/{application_id}/interview", json=_payload(admin_id)
        )
    ).json()
    row = (
        await db_session.execute(select(Interview).where(Interview.id == uuid.UUID(first["id"])))
    ).scalar_one()

    def clone(round_number: int) -> Interview:
        return Interview(
            company_id=row.company_id,
            application_id=row.application_id,
            interviewer_user_id=row.interviewer_user_id,
            round_number=round_number,
            duration_minutes=30,
            timezone="Europe/Berlin",
        )

    db_session.add(clone(2))
    await db_session.commit()  # a different round is fine
    db_session.add(clone(1))
    with pytest.raises(IntegrityError):
        await db_session.commit()
