"""Interview admin endpoints; Google Calendar is faked at the service seam."""

from datetime import datetime
from uuid import uuid4

import httpx
import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.security import read_interview_token
from app.models import User
from app.services import google_calendar
from app.services import interviews as interviews_service
from tests.db import database_reachable, s3_reachable

pytestmark = pytest.mark.skipif(
    not (database_reachable() and s3_reachable()),
    reason="database and object storage required (start postgres+minio or use CI)",
)

PDF_BYTES = b"%PDF-1.4 interview flow"


@pytest.fixture
def multi_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "mode", "multi")


@pytest.fixture
def quiet_freebusy(monkeypatch: pytest.MonkeyPatch) -> None:
    async def freebusy(
        db: AsyncSession, user: User, start: datetime, end: datetime
    ) -> list[tuple[datetime, datetime]]:
        return []

    monkeypatch.setattr(interviews_service.google_calendar, "freebusy", freebusy)


async def _company_with_applicant(client: AsyncClient) -> tuple[str, str, str]:
    """Register company, publish job, apply as candidate; returns
    (application_id, admin_user_id, admin_email), logged in as admin."""
    creds = {
        "email": f"admin-{uuid4().hex[:8]}@vetd-ci.dev",
        "password": "a-long-secure-password",
    }
    name = f"Iv Co {uuid4().hex[:6]}"
    resp = await client.post("/api/v1/auth/register", json={"company_name": name, **creds})
    assert resp.status_code == 201, resp.text
    admin_user_id = resp.json()["id"]
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
    application_id = (await client.get("/api/v1/applications")).json()["items"][0]["id"]
    return application_id, admin_user_id, creds["email"]


async def _connect_calendar(db: AsyncSession, user_id: str, email: str) -> User:
    user = (await db.execute(select(User).where(User.email == email))).scalar_one()
    await google_calendar.store_credentials(db, user, refresh_token="1//r", google_email=email)
    return user


@pytest.mark.usefixtures("migrated_db", "bucket", "multi_mode", "quiet_freebusy")
async def test_slot_preview_requires_connected_calendar(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    application_id, admin_id, admin_email = await _company_with_applicant(client)

    async def no_credential(
        db: AsyncSession, user: User, start: datetime, end: datetime
    ) -> list[tuple[datetime, datetime]]:
        raise google_calendar.NeedsReconnectError("not connected")

    monkeypatch.setattr(interviews_service.google_calendar, "freebusy", no_credential)
    resp = await client.post(
        f"/api/v1/applications/{application_id}/interview/slot-preview",
        json={
            "interviewer_user_id": admin_id,
            "duration_minutes": 45,
            "timezone": "Europe/Berlin",
        },
    )
    assert resp.status_code == 409
    assert "Calendar" in resp.json()["detail"]


@pytest.mark.usefixtures("migrated_db", "bucket", "multi_mode", "quiet_freebusy")
async def test_slot_preview_returns_summary(client: AsyncClient) -> None:
    application_id, admin_id, _ = await _company_with_applicant(client)
    resp = await client.post(
        f"/api/v1/applications/{application_id}/interview/slot-preview",
        json={
            "interviewer_user_id": admin_id,
            "duration_minutes": 45,
            "timezone": "Europe/Berlin",
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["schedule_summary"] == "Mon–Fri 09:00–17:00 (Europe/Berlin)"
    assert body["open_slot_count"] > 0


@pytest.mark.usefixtures("migrated_db", "bucket", "multi_mode", "quiet_freebusy")
async def test_create_interview_sends_booking_email(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.services import email as email_service

    application_id, admin_id, admin_email = await _company_with_applicant(client)
    await _connect_calendar(db_session, admin_id, admin_email)
    sent: list[dict[str, object]] = []
    monkeypatch.setattr(
        email_service,
        "send_interview_invite",
        lambda **kw: sent.append(kw),
    )
    resp = await client.post(
        f"/api/v1/applications/{application_id}/interview",
        json={
            "interviewer_user_id": admin_id,
            "duration_minutes": 45,
            "timezone": "Europe/Berlin",
            "description": "Your work, our stack.",
        },
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["status"] == "pending"
    assert body["interviewer_email"] == admin_email
    assert "offered_slots" not in body
    assert len(sent) == 1
    booking_url = str(sent[0]["booking_url"])
    token = booking_url.rsplit("/", 1)[-1]
    assert str(read_interview_token(token)) == body["id"]

    got = await client.get(f"/api/v1/applications/{application_id}/interview")
    assert got.json()["id"] == body["id"]


@pytest.mark.usefixtures("migrated_db", "bucket", "multi_mode", "quiet_freebusy")
async def test_create_interview_requires_connected_calendar(client: AsyncClient) -> None:
    application_id, admin_id, _ = await _company_with_applicant(client)
    resp = await client.post(
        f"/api/v1/applications/{application_id}/interview",
        json={
            "interviewer_user_id": admin_id,
            "duration_minutes": 30,
            "timezone": "Europe/Berlin",
        },
    )
    assert resp.status_code == 409


@pytest.mark.usefixtures("migrated_db", "bucket", "multi_mode", "quiet_freebusy")
async def test_second_active_interview_conflicts(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.services import email as email_service

    application_id, admin_id, admin_email = await _company_with_applicant(client)
    await _connect_calendar(db_session, admin_id, admin_email)
    monkeypatch.setattr(email_service, "send_interview_invite", lambda **kw: None)
    payload = {
        "interviewer_user_id": admin_id,
        "duration_minutes": 30,
        "timezone": "Europe/Berlin",
    }
    first = await client.post(f"/api/v1/applications/{application_id}/interview", json=payload)
    assert first.status_code == 201
    second = await client.post(f"/api/v1/applications/{application_id}/interview", json=payload)
    assert second.status_code == 409


@pytest.mark.usefixtures("migrated_db", "bucket", "multi_mode", "quiet_freebusy")
async def test_cancel_interview_notifies_and_allows_recreate(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.services import email as email_service

    application_id, admin_id, admin_email = await _company_with_applicant(client)
    await _connect_calendar(db_session, admin_id, admin_email)
    monkeypatch.setattr(email_service, "send_interview_invite", lambda **kw: None)
    cancelled: list[dict[str, object]] = []
    monkeypatch.setattr(
        email_service, "send_interview_cancelled", lambda **kw: cancelled.append(kw)
    )
    payload = {
        "interviewer_user_id": admin_id,
        "duration_minutes": 30,
        "timezone": "Europe/Berlin",
    }
    created = await client.post(f"/api/v1/applications/{application_id}/interview", json=payload)
    assert created.status_code == 201

    resp = await client.post(f"/api/v1/applications/{application_id}/interview/cancel")
    assert resp.status_code == 200
    assert resp.json()["status"] == "cancelled"
    assert len(cancelled) == 1
    assert (await client.get(f"/api/v1/applications/{application_id}/interview")).json() is None

    again = await client.post(f"/api/v1/applications/{application_id}/interview", json=payload)
    assert again.status_code == 201


@pytest.mark.usefixtures("migrated_db", "bucket", "multi_mode", "quiet_freebusy")
async def test_cancel_without_active_interview_404s(client: AsyncClient) -> None:
    application_id, _, _ = await _company_with_applicant(client)
    resp = await client.post(f"/api/v1/applications/{application_id}/interview/cancel")
    assert resp.status_code == 404


@pytest.mark.usefixtures("migrated_db", "bucket", "multi_mode", "quiet_freebusy")
async def test_interview_endpoints_are_tenant_scoped(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The interviews admin API was the only tenant-owned family without a
    cross-tenant test. A foreign company gets 404 on every endpoint — never
    a 409 or data — and a foreign interviewer is invisible even on your own
    application."""
    from app.services import email as email_service

    application_id, admin_id, admin_email = await _company_with_applicant(client)
    await _connect_calendar(db_session, admin_id, admin_email)
    monkeypatch.setattr(email_service, "send_interview_invite", lambda **kw: None)
    created = await client.post(
        f"/api/v1/applications/{application_id}/interview",
        json={
            "interviewer_user_id": admin_id,
            "duration_minutes": 45,
            "timezone": "Europe/Berlin",
        },
    )
    assert created.status_code == 201, created.text

    # a second company; _company_with_applicant leaves us logged in as ITS admin
    other_app_id, other_admin_id, _ = await _company_with_applicant(client)

    slot_payload = {
        "interviewer_user_id": other_admin_id,
        "duration_minutes": 30,
        "timezone": "Europe/Berlin",
    }
    preview = await client.post(
        f"/api/v1/applications/{application_id}/interview/slot-preview", json=slot_payload
    )
    assert preview.status_code == 404
    create = await client.post(
        f"/api/v1/applications/{application_id}/interview", json=slot_payload
    )
    assert create.status_code == 404
    assert (await client.get(f"/api/v1/applications/{application_id}/interview")).status_code == 404
    assert (
        await client.post(f"/api/v1/applications/{application_id}/interview/cancel")
    ).status_code == 404

    # the FIRST company's interviewer must not resolve on the second's application
    foreign_interviewer = {
        "interviewer_user_id": admin_id,
        "duration_minutes": 30,
        "timezone": "Europe/Berlin",
    }
    resp = await client.post(
        f"/api/v1/applications/{other_app_id}/interview/slot-preview", json=foreign_interviewer
    )
    assert resp.status_code == 404
    resp = await client.post(
        f"/api/v1/applications/{other_app_id}/interview", json=foreign_interviewer
    )
    assert resp.status_code == 404
