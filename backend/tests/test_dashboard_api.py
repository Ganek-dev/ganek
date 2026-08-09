"""Dashboard v2 feeds: activity log, manual tasks, Today panel."""

from datetime import UTC, datetime, time, timedelta
from uuid import uuid4

import httpx
import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models import Interview, InterviewStatus, User
from app.services import google_calendar
from tests.db import database_reachable, s3_reachable

pytestmark = pytest.mark.skipif(
    not (database_reachable() and s3_reachable()),
    reason="database and object storage required (start postgres+minio or use CI)",
)

PDF_BYTES = b"%PDF-1.4 dashboard flow"


@pytest.fixture
def multi_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "mode", "multi")


async def _company_with_applicant(client: AsyncClient) -> tuple[str, str, str]:
    """Returns (application_id, admin_user_id, admin_email), logged in as admin."""
    creds = {
        "email": f"admin-{uuid4().hex[:8]}@vetd-ci.dev",
        "password": "a-long-secure-password",
    }
    name = f"Dash Co {uuid4().hex[:6]}"
    resp = await client.post("/api/v1/auth/register", json={"company_name": name, **creds})
    assert resp.status_code == 201, resp.text
    admin_id = resp.json()["id"]
    slug = name.lower().replace(" ", "-")

    job = (await client.post("/api/v1/jobs", json={"title": "Backend Engineer"})).json()
    assert (await client.post(f"/api/v1/jobs/{job['id']}/publish")).status_code == 200
    await client.post("/api/v1/auth/logout")

    base = f"/api/v1/public/companies/{slug}/jobs/{job['slug']}"
    ticket = (await client.post(f"{base}/apply/upload-url")).json()
    async with httpx.AsyncClient() as raw:
        put = await raw.put(
            ticket["upload_url"],
            content=PDF_BYTES,
            headers={"Content-Type": ticket["content_type"]},
        )
        assert put.status_code == 200
    resp = await client.post(
        f"{base}/apply",
        json={
            "name": "Marta Vidal",
            "email": f"cand-{uuid4().hex[:8]}@vetd-ci.dev",
            "cv_object_key": ticket["object_key"],
            "cv_filename": "marta.pdf",
        },
    )
    assert resp.status_code == 201, resp.text

    assert (await client.post("/api/v1/auth/login", json=creds)).status_code == 200
    application_id = (await client.get("/api/v1/applications")).json()[0]["id"]
    return application_id, admin_id, creds["email"]


@pytest.mark.usefixtures("migrated_db", "bucket", "multi_mode")
async def test_activity_records_apply_and_stage_change(client: AsyncClient) -> None:
    application_id, _, admin_email = await _company_with_applicant(client)
    resp = await client.patch(
        f"/api/v1/applications/{application_id}/stage",
        json={"stage": "screening", "notify_candidate": False},
    )
    assert resp.status_code == 200

    feed = (await client.get("/api/v1/activity")).json()
    types = [row["type"] for row in feed]
    assert types[0] == "stage.changed"  # newest first
    assert "application.received" in types
    stage_row = feed[0]
    assert stage_row["actor_email"] == admin_email
    assert stage_row["payload"] == {"from": "new", "to": "screening"}
    received = next(row for row in feed if row["type"] == "application.received")
    assert received["actor_email"] is None  # candidate action
    assert received["payload"]["candidate"] == "Marta Vidal"


@pytest.mark.usefixtures("migrated_db", "bucket", "multi_mode")
async def test_activity_limit_clamped(client: AsyncClient) -> None:
    await _company_with_applicant(client)
    resp = await client.get("/api/v1/activity?limit=9999")
    assert resp.status_code == 200
    assert len(resp.json()) <= 50


@pytest.mark.usefixtures("migrated_db", "bucket", "multi_mode")
async def test_tasks_crud_and_tenancy(client: AsyncClient) -> None:
    await _company_with_applicant(client)
    created = await client.post(
        "/api/v1/tasks",
        json={"title": "Call Marta about the offer", "note": "before Friday"},
    )
    assert created.status_code == 201, created.text
    task = created.json()
    assert task["done_at"] is None

    open_tasks = (await client.get("/api/v1/tasks")).json()
    assert [t["id"] for t in open_tasks] == [task["id"]]

    done = await client.patch(f"/api/v1/tasks/{task['id']}", json={"done": True})
    assert done.json()["done_at"] is not None
    assert (await client.get("/api/v1/tasks")).json() == []
    assert len((await client.get("/api/v1/tasks?include_done=true")).json()) == 1

    reopened = await client.patch(f"/api/v1/tasks/{task['id']}", json={"done": False})
    assert reopened.json()["done_at"] is None
    assert (await client.delete(f"/api/v1/tasks/{task['id']}")).status_code == 204
    assert (await client.get("/api/v1/tasks")).json() == []

    # a second company must see none of this company's rows
    await client.post("/api/v1/auth/logout")
    await _company_with_applicant(client)
    assert (await client.get("/api/v1/tasks?include_done=true")).json() == []
    foreign = [row["type"] for row in (await client.get("/api/v1/activity")).json()]
    assert foreign == ["application.received"]


@pytest.mark.usefixtures("migrated_db", "bucket", "multi_mode")
async def test_today_prefers_google_when_connected(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, admin_id, admin_email = await _company_with_applicant(client)
    user = (await db_session.execute(select(User).where(User.email == admin_email))).scalar_one()
    await google_calendar.store_credentials(
        db_session, user, refresh_token="1//r", google_email=admin_email
    )

    async def fake_today(db: AsyncSession, u: User, *, tz: str) -> list[dict[str, object]]:
        return [{"start": "2026-08-08T11:00:00+02:00", "summary": "Intro call — Marta"}]

    monkeypatch.setattr(google_calendar, "list_today_events", fake_today)
    resp = await client.get("/api/v1/stats/today?tz=Europe/Berlin")
    body = resp.json()
    assert body["source"] == "google"
    assert body["events"][0]["summary"] == "Intro call — Marta"


@pytest.mark.usefixtures("migrated_db", "bucket", "multi_mode")
async def test_today_falls_back_to_vetd_interviews(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    application_id, admin_id, _ = await _company_with_applicant(client)
    from app.models import Application

    company_id = (
        await db_session.execute(
            select(Application.company_id).where(Application.id == application_id)
        )
    ).scalar_one()
    interview = Interview(
        company_id=company_id,
        application_id=application_id,
        interviewer_user_id=admin_id,
        duration_minutes=45,
        timezone="UTC",
        status=InterviewStatus.BOOKED,
        # keep the slot inside TODAY in UTC even when the suite runs near
        # midnight — now+2h would flake past 22:00 UTC otherwise
        scheduled_start=max(
            min(
                datetime.now(UTC) + timedelta(hours=2),
                datetime.combine(datetime.now(UTC).date(), time(23, 30), tzinfo=UTC),
            ),
            datetime.now(UTC) + timedelta(minutes=1),
        ),
        meet_url="https://meet.google.com/xyz",
    )
    db_session.add(interview)
    await db_session.commit()

    resp = await client.get("/api/v1/stats/today?tz=not-a-real-zone")  # bad tz → UTC
    body = resp.json()
    assert body["source"] == "vetd"
    assert len(body["events"]) == 1
    assert "Marta Vidal" in body["events"][0]["summary"]
    assert body["events"][0]["hangout_link"] == "https://meet.google.com/xyz"


@pytest.mark.usefixtures("migrated_db", "bucket", "multi_mode")
async def test_today_empty_without_anything(client: AsyncClient) -> None:
    await _company_with_applicant(client)
    body = (await client.get("/api/v1/stats/today")).json()
    assert body == {"source": "vetd", "events": []}
