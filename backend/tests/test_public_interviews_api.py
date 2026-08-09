"""Candidate booking endpoints; Google faked at the google_calendar seam."""

import uuid
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import httpx
import pytest
from httpx import AsyncClient
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import settings
from app.models import Application, Company, Interview, InterviewStatus, User
from app.services import google_calendar
from app.services import interviews as interviews_service
from tests.db import database_reachable, s3_reachable

pytestmark = pytest.mark.skipif(
    not (database_reachable() and s3_reachable()),
    reason="database and object storage required (start postgres+minio or use CI)",
)

PDF_BYTES = b"%PDF-1.4 booking flow"


@pytest.fixture
def multi_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "mode", "multi")


@pytest.fixture
def quiet_google(monkeypatch: pytest.MonkeyPatch) -> None:
    """Silence Google: empty free/busy + a canned Meet event everywhere."""

    async def freebusy(
        db: AsyncSession, user: User, start: datetime, end: datetime
    ) -> list[tuple[datetime, datetime]]:
        return []

    async def create_meet_event(*args: object, **kwargs: object) -> tuple[str, str]:
        return "evt-1", "https://meet.google.com/abc-defg-hij"

    async def patch_event_time(*args: object, **kwargs: object) -> None:
        return None

    async def delete_event(*args: object, **kwargs: object) -> None:
        return None

    for module in (interviews_service.google_calendar,):
        monkeypatch.setattr(module, "freebusy", freebusy)
        monkeypatch.setattr(module, "create_meet_event", create_meet_event)
        monkeypatch.setattr(module, "patch_event_time", patch_event_time)
        monkeypatch.setattr(module, "delete_event", delete_event)


async def _register_and_publish(
    client: AsyncClient, company_prefix: str
) -> tuple[str, str, dict[str, object], dict[str, str]]:
    """Register a company/admin and publish one job. Returns
    (admin_id, slug, job, creds), logged OUT."""
    creds = {
        "email": f"admin-{uuid4().hex[:8]}@vetd-ci.dev",
        "password": "a-long-secure-password",
    }
    name = f"{company_prefix} {uuid4().hex[:6]}"
    resp = await client.post("/api/v1/auth/register", json={"company_name": name, **creds})
    assert resp.status_code == 201, resp.text
    admin_id = resp.json()["id"]
    slug = name.lower().replace(" ", "-")

    job = (await client.post("/api/v1/jobs", json={"title": "Backend Engineer"})).json()
    assert (await client.post(f"/api/v1/jobs/{job['id']}/publish")).status_code == 200
    await client.post("/api/v1/auth/logout")
    return admin_id, slug, job, creds


async def _apply_as_candidate(
    client: AsyncClient, slug: str, job_slug: str, candidate_name: str
) -> None:
    base = f"/api/v1/public/companies/{slug}/jobs/{job_slug}"
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
            "name": candidate_name,
            "email": f"cand-{uuid4().hex[:8]}@vetd-ci.dev",
            "cv_object_key": ticket["object_key"],
            "cv_filename": "cv.pdf",
        },
    )
    assert resp.status_code == 201, resp.text


async def _booking_token(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> tuple[str, list[str]]:
    """Admin sets up company/job/applicant/interview; returns (token, slots)
    — the currently live-offered slots — logged OUT so subsequent calls are
    anonymous candidate traffic."""
    from app.services import email as email_service

    admin_id, slug, job, creds = await _register_and_publish(client, "Book Co")
    await _apply_as_candidate(client, slug, str(job["slug"]), "Marta Vidal")

    assert (await client.post("/api/v1/auth/login", json=creds)).status_code == 200
    application_id = (await client.get("/api/v1/applications")).json()[0]["id"]

    user = (await db_session.execute(select(User).where(User.email == creds["email"]))).scalar_one()
    await google_calendar.store_credentials(
        db_session, user, refresh_token="1//r", google_email=creds["email"]
    )
    captured: list[dict[str, object]] = []
    monkeypatch.setattr(email_service, "send_interview_invite", lambda **kw: captured.append(kw))
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
    token = str(captured[0]["booking_url"]).rsplit("/", 1)[-1]
    context = await client.get(f"/api/v1/public/interviews/{token}")
    assert context.status_code == 200, context.text
    slots = context.json()["available_slots"]
    assert len(slots) > 0
    await client.post("/api/v1/auth/logout")
    return token, slots


async def _two_applications(
    client: AsyncClient, db_session: AsyncSession
) -> tuple[User, Company, Application, Application]:
    """One company/admin (the interviewer), two candidates applying to the
    same published job. Returns ORM rows fetched fresh from `db_session`;
    logged out at the end so subsequent calls are anonymous."""
    admin_id, slug, job, creds = await _register_and_publish(client, "Race Co")
    for candidate_name in ("Marta Vidal", "Jonas Weber"):
        await _apply_as_candidate(client, slug, str(job["slug"]), candidate_name)

    assert (await client.post("/api/v1/auth/login", json=creds)).status_code == 200
    applications = (await client.get("/api/v1/applications")).json()
    assert len(applications) == 2
    await client.post("/api/v1/auth/logout")

    interviewer = (
        await db_session.execute(select(User).where(User.id == uuid.UUID(admin_id)))
    ).scalar_one()
    company = (
        await db_session.execute(select(Company).where(Company.id == interviewer.company_id))
    ).scalar_one()
    application_rows = []
    for row in applications:
        result = await db_session.execute(
            select(Application).where(Application.id == uuid.UUID(row["id"]))
        )
        application_rows.append(result.scalar_one())
    application_one, application_two = application_rows
    return interviewer, company, application_one, application_two


@pytest.mark.usefixtures("migrated_db", "bucket", "multi_mode", "quiet_google")
async def test_booked_vetd_interview_blocks_second_booking_despite_freebusy_lag(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """Two candidates, same interviewer, same slot; Google freebusy stays empty
    (simulating propagation lag) — the vetd-side booked row must still win."""
    interviewer, company, application_one, application_two = await _two_applications(
        client, db_session
    )
    interview_one = await interviews_service.create_interview(
        db_session,
        company,
        application_one,
        interviewer=interviewer,
        title="Hiring manager interview",
        description="",
        duration_minutes=30,
        timezone="Europe/Berlin",
    )
    interview_two = await interviews_service.create_interview(
        db_session,
        company,
        application_two,
        interviewer=interviewer,
        title="Hiring manager interview",
        description="",
        duration_minutes=30,
        timezone="Europe/Berlin",
    )

    slots = await interviews_service.generate_slots(
        db_session, interviewer, duration_minutes=30, timezone="Europe/Berlin"
    )
    target = slots[0]

    booked_view = await interviews_service.get_by_id_public(db_session, interview_one.id)
    assert booked_view is not None
    await interviews_service.book(db_session, booked_view, start=target)

    contested_view = await interviews_service.get_by_id_public(db_session, interview_two.id)
    assert contested_view is not None
    with pytest.raises(interviews_service.SlotUnavailableError):
        await interviews_service.book(db_session, contested_view, start=target)


@pytest.mark.usefixtures("migrated_db", "bucket", "multi_mode", "quiet_google")
async def test_book_rechecks_status_under_lock_against_concurrent_commit(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Double-submit / two-tabs race: a concurrent session books the
    interview and commits AFTER our caller loaded `interview` (which is
    stale in-memory, expire_on_commit=False) but BEFORE `book()` runs. The
    post-lock re-read must catch this — no second Meet event, no
    overwritten scheduled_start/google_event_id."""
    interviewer, company, application_one, _ = await _two_applications(client, db_session)
    interview = await interviews_service.create_interview(
        db_session,
        company,
        application_one,
        interviewer=interviewer,
        title="Hiring manager interview",
        description="",
        duration_minutes=30,
        timezone="Europe/Berlin",
    )
    slots = await interviews_service.generate_slots(
        db_session, interviewer, duration_minutes=30, timezone="Europe/Berlin"
    )
    stale_view = await interviews_service.get_by_id_public(db_session, interview.id)
    assert stale_view is not None
    assert stale_view.status is InterviewStatus.PENDING  # loaded before the concurrent write

    # A different request, on a different DB connection, already booked
    # this exact interview and committed — simulating the losing tab of a
    # double-submit that got there first.
    other_engine = create_async_engine(settings.database_url, poolclass=NullPool)
    other_factory = async_sessionmaker(other_engine, expire_on_commit=False)
    async with other_factory() as other_db:
        await other_db.execute(
            text(
                "UPDATE interviews SET status = 'booked', scheduled_start = :start, "
                "google_event_id = 'evt-concurrent', "
                "meet_url = 'https://meet.example/concurrent' WHERE id = :id"
            ),
            {"start": slots[1], "id": interview.id},
        )
        await other_db.commit()
    await other_engine.dispose()

    calls: list[object] = []

    async def tracking_create_meet_event(*args: object, **kwargs: object) -> tuple[str, str]:
        calls.append((args, kwargs))
        return "evt-should-not-happen", "https://meet.example/should-not-happen"

    monkeypatch.setattr(
        interviews_service.google_calendar, "create_meet_event", tracking_create_meet_event
    )

    with pytest.raises(interviews_service.AlreadyBookedError):
        await interviews_service.book(db_session, stale_view, start=slots[0])

    assert calls == []  # no orphaned second Meet event was ever created
    row = (
        await db_session.execute(
            select(Interview.status, Interview.scheduled_start, Interview.google_event_id).where(
                Interview.id == interview.id
            )
        )
    ).one()
    assert row.status == InterviewStatus.BOOKED
    assert row.google_event_id == "evt-concurrent"
    assert row.scheduled_start == slots[1]


@pytest.mark.usefixtures("migrated_db", "bucket", "multi_mode", "quiet_google")
async def test_booking_context(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    token, slots = await _booking_token(client, db_session, monkeypatch)
    resp = await client.get(f"/api/v1/public/interviews/{token}")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "pending"
    assert body["candidate_first_name"] == "Marta"
    assert body["duration_minutes"] == 45
    assert body["timezone"] == "Europe/Berlin"
    assert len(body["available_slots"]) > 0
    assert body["meet_url"] is None
    assert "Book Co" in body["company_name"]


@pytest.mark.usefixtures("migrated_db", "bucket", "multi_mode", "quiet_google")
async def test_book_happy_path(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    token, slots = await _booking_token(client, db_session, monkeypatch)
    resp = await client.post(f"/api/v1/public/interviews/{token}/book", json={"start": slots[1]})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "booked"
    assert body["meet_url"] == "https://meet.google.com/abc-defg-hij"
    assert body["scheduled_start"] is not None

    again = await client.post(f"/api/v1/public/interviews/{token}/book", json={"start": slots[0]})
    assert again.status_code == 409
    assert again.json()["detail"] == "already-booked"


@pytest.mark.usefixtures("migrated_db", "bucket", "multi_mode", "quiet_google")
async def test_book_rejects_unoffered_slot(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    token, _ = await _booking_token(client, db_session, monkeypatch)
    rogue = (datetime.now(UTC) + timedelta(days=5)).isoformat()
    resp = await client.post(f"/api/v1/public/interviews/{token}/book", json={"start": rogue})
    assert resp.status_code == 409
    assert resp.json()["detail"] == "slot-taken"


@pytest.mark.usefixtures("migrated_db", "bucket", "multi_mode", "quiet_google")
async def test_book_rejects_busy_slot(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    token, slots = await _booking_token(client, db_session, monkeypatch)
    chosen = datetime.fromisoformat(slots[0])

    async def busy_now(
        db: AsyncSession, user: User, start: datetime, end: datetime
    ) -> list[tuple[datetime, datetime]]:
        return [(chosen, chosen + timedelta(minutes=45))]

    monkeypatch.setattr(interviews_service.google_calendar, "freebusy", busy_now)
    resp = await client.post(f"/api/v1/public/interviews/{token}/book", json={"start": slots[0]})
    assert resp.status_code == 409
    assert resp.json()["detail"] == "slot-taken"


@pytest.mark.usefixtures("migrated_db", "bucket", "multi_mode", "quiet_google")
async def test_reschedule_and_cancel(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    token, slots = await _booking_token(client, db_session, monkeypatch)

    early = await client.post(
        f"/api/v1/public/interviews/{token}/reschedule", json={"start": slots[0]}
    )
    assert early.status_code == 409
    assert early.json()["detail"] == "not-booked"

    assert (
        await client.post(f"/api/v1/public/interviews/{token}/book", json={"start": slots[0]})
    ).status_code == 200
    moved = await client.post(
        f"/api/v1/public/interviews/{token}/reschedule", json={"start": slots[2]}
    )
    assert moved.status_code == 200, moved.text
    # both are the same instant, but scheduled_start is normalized to UTC
    # while the offered slot carries the interviewer's local offset.
    assert datetime.fromisoformat(moved.json()["scheduled_start"]) == datetime.fromisoformat(
        slots[2]
    )

    cancelled = await client.post(f"/api/v1/public/interviews/{token}/cancel")
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelled"
    # idempotent second cancel
    assert (await client.post(f"/api/v1/public/interviews/{token}/cancel")).status_code == 200
    context = await client.get(f"/api/v1/public/interviews/{token}")
    assert context.json()["status"] == "cancelled"
    assert context.json()["available_slots"] == []


@pytest.mark.usefixtures("migrated_db", "bucket", "multi_mode", "quiet_google")
async def test_book_when_google_breaks_is_503(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    token, slots = await _booking_token(client, db_session, monkeypatch)

    async def broken(*args: object, **kwargs: object) -> tuple[str, str]:
        raise google_calendar.NeedsReconnectError("consent revoked")

    monkeypatch.setattr(interviews_service.google_calendar, "create_meet_event", broken)
    resp = await client.post(f"/api/v1/public/interviews/{token}/book", json={"start": slots[0]})
    assert resp.status_code == 503


@pytest.mark.usefixtures("migrated_db", "bucket", "multi_mode", "quiet_google")
async def test_public_get_survives_calendar_outage(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A candidate opening the booking page must still get a 200 with an
    empty slot list when Google is down — not a 503 (live_slots swallows it)."""
    token, _ = await _booking_token(client, db_session, monkeypatch)

    async def boom(*args: object, **kwargs: object) -> None:
        raise google_calendar.GoogleCalendarError("down")

    monkeypatch.setattr(interviews_service.google_calendar, "freebusy", boom)
    resp = await client.get(f"/api/v1/public/interviews/{token}")
    assert resp.status_code == 200
    assert resp.json()["available_slots"] == []


async def test_bad_token_404s(client: AsyncClient) -> None:
    resp = await client.get("/api/v1/public/interviews/garbage")
    assert resp.status_code == 404
