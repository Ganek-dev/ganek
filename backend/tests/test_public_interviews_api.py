"""Candidate booking endpoints: slots, booking, reschedule, cancel, the
concurrency guarantees, and the mails the routes queue."""

import asyncio
import uuid
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import settings
from app.core.security import create_interview_token, read_interview_token
from app.models import Application, Company, EmailOutbox, Interview, InterviewStatus, User
from app.services import interviews as interviews_service
from tests.db import database_reachable, s3_reachable
from tests.helpers import upload_pdf

pytestmark = pytest.mark.skipif(
    not (database_reachable() and s3_reachable()),
    reason="database and object storage required (start postgres+minio or use CI)",
)

PDF_BYTES = b"%PDF-1.4 booking flow"


@pytest.fixture
def multi_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "mode", "multi")


async def _register_and_publish(
    client: AsyncClient, company_prefix: str
) -> tuple[str, str, dict[str, object], dict[str, str]]:
    """Register a company/admin and publish one job. Returns
    (admin_id, slug, job, creds), logged OUT."""
    creds = {
        "email": f"admin-{uuid4().hex[:8]}@ganek-ci.dev",
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
    assert (await upload_pdf(ticket, PDF_BYTES)).is_success
    resp = await client.post(
        f"{base}/apply",
        json={
            "name": candidate_name,
            "email": f"cand-{uuid4().hex[:8]}@ganek-ci.dev",
            "cv_object_key": ticket["object_key"],
            "cv_filename": "cv.pdf",
        },
    )
    assert resp.status_code == 201, resp.text


async def _booking_token(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> tuple[str, list[str]]:
    """Admin sets up company/job/applicant/interview; returns (token, slots)
    - the currently live-offered slots - logged OUT so subsequent calls are
    anonymous candidate traffic."""
    from app.services import email as email_service

    admin_id, slug, job, creds = await _register_and_publish(client, "Book Co")
    await _apply_as_candidate(client, slug, str(job["slug"]), "Marta Vidal")

    assert (await client.post("/api/v1/auth/login", json=creds)).status_code == 200
    application_id = (await client.get("/api/v1/applications")).json()["items"][0]["id"]

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
    applications = (await client.get("/api/v1/applications")).json()["items"]
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


@pytest.mark.usefixtures("migrated_db", "bucket", "multi_mode")
async def test_booked_interview_blocks_second_booking_of_the_same_slot(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """Two candidates, same interviewer, same slot: the booked row wins."""
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


@pytest.mark.usefixtures("migrated_db", "bucket", "multi_mode")
async def test_book_rechecks_status_under_lock_against_concurrent_commit(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """Double-submit / two-tabs race: a concurrent session books the
    interview and commits AFTER our caller loaded `interview` (which is
    stale in-memory, expire_on_commit=False) but BEFORE `book()` runs. The
    post-lock re-read must catch this - no overwritten scheduled_start."""
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
    # this exact interview and committed - simulating the losing tab of a
    # double-submit that got there first.
    other_engine = create_async_engine(settings.database_url, poolclass=NullPool)
    other_factory = async_sessionmaker(other_engine, expire_on_commit=False)
    async with other_factory() as other_db:
        await other_db.execute(
            text(
                "UPDATE interviews SET status = 'booked', scheduled_start = :start WHERE id = :id"
            ),
            {"start": slots[1], "id": interview.id},
        )
        await other_db.commit()
    await other_engine.dispose()

    with pytest.raises(interviews_service.AlreadyBookedError):
        await interviews_service.book(db_session, stale_view, start=slots[0])

    row = (
        await db_session.execute(
            select(Interview.status, Interview.scheduled_start).where(Interview.id == interview.id)
        )
    ).one()
    assert row.status == InterviewStatus.BOOKED
    assert row.scheduled_start == slots[1]


@pytest.mark.usefixtures("migrated_db", "bucket", "multi_mode")
async def test_book_lock_serializes_concurrent_booking_across_applications(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Genuine two-session race: two DIFFERENT applications with the SAME
    interviewer both try to book the SAME target slot via `asyncio.gather`,
    each on its own DB connection - nothing but `pg_advisory_xact_lock`
    inside `_lock_interviewer` can serialize this (unlike the two tests
    above, both of which drive their two `book()` calls sequentially and so
    never actually contend on the lock).

    `_require_available` is slowed down so both callers see the slot free
    at the same time, then contend on `pg_advisory_xact_lock`. The winner
    books and commits; the loser gets the lock afterwards and
    `_require_unbooked` finds the winner's row. Delete `_lock_interviewer`
    (or the under-lock DB re-check) and both commits land - two successes
    - which is what this test would then catch instead of passing by
    accident of execution order.
    """
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

    real_require_available = interviews_service._require_available

    async def slow_require_available(
        db: AsyncSession, interview: Interview, start: datetime
    ) -> None:
        await asyncio.sleep(0.2)
        await real_require_available(db, interview, start)

    monkeypatch.setattr(interviews_service, "_require_available", slow_require_available)

    slots = await interviews_service.generate_slots(
        db_session, interviewer, duration_minutes=30, timezone="Europe/Berlin"
    )
    target = slots[0]

    other_engine = create_async_engine(settings.database_url, poolclass=NullPool)
    other_factory = async_sessionmaker(other_engine, expire_on_commit=False)

    async def _book_on(session: AsyncSession, interview_id: uuid.UUID) -> Interview:
        # each session loads its OWN Interview instance - book() mutates
        # in-memory attributes, so sharing one ORM object across sessions
        # would mask the very race this test exists to exercise.
        view = await interviews_service.get_by_id_public(session, interview_id)
        assert view is not None
        return await interviews_service.book(session, view, start=target)

    try:
        async with other_factory() as other_db:
            results = await asyncio.gather(
                _book_on(db_session, interview_one.id),
                _book_on(other_db, interview_two.id),
                return_exceptions=True,
            )
    finally:
        await other_engine.dispose()

    successes = [r for r in results if isinstance(r, Interview)]
    failures = [r for r in results if isinstance(r, BaseException)]
    assert len(successes) == 1, results
    assert len(failures) == 1, results
    assert isinstance(failures[0], interviews_service.SlotUnavailableError), results

    booked_rows = (
        (
            await db_session.execute(
                select(Interview).where(
                    Interview.interviewer_user_id == interviewer.id,
                    Interview.status == InterviewStatus.BOOKED,
                    Interview.scheduled_start == target,
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(booked_rows) == 1


@pytest.mark.usefixtures("migrated_db", "bucket", "multi_mode")
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
    assert body["location"] == ""
    assert "Book Co" in body["company_name"]


@pytest.mark.usefixtures("migrated_db", "bucket", "multi_mode")
async def test_book_happy_path(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    token, slots = await _booking_token(client, db_session, monkeypatch)
    resp = await client.post(f"/api/v1/public/interviews/{token}/book", json={"start": slots[1]})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "booked"
    assert body["scheduled_start"] is not None

    again = await client.post(f"/api/v1/public/interviews/{token}/book", json={"start": slots[0]})
    assert again.status_code == 409
    assert again.json()["detail"] == "already-booked"


@pytest.mark.usefixtures("migrated_db", "bucket", "multi_mode")
async def test_book_rejects_unoffered_slot(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    token, _ = await _booking_token(client, db_session, monkeypatch)
    rogue = (datetime.now(UTC) + timedelta(days=5)).isoformat()
    resp = await client.post(f"/api/v1/public/interviews/{token}/book", json={"start": rogue})
    assert resp.status_code == 409
    assert resp.json()["detail"] == "slot-taken"


@pytest.mark.usefixtures("migrated_db", "bucket", "multi_mode")
async def test_book_rejects_slot_booked_meanwhile(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """The slot list the candidate saw is stale: another candidate of the
    same interviewer booked the window in between."""
    interviewer, company, application_one, application_two = await _two_applications(
        client, db_session
    )
    first = await interviews_service.create_interview(
        db_session,
        company,
        application_one,
        interviewer=interviewer,
        title="Hiring manager interview",
        description="",
        duration_minutes=30,
        timezone="Europe/Berlin",
    )
    second = await interviews_service.create_interview(
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
    second_view = await interviews_service.get_by_id_public(db_session, second.id)
    assert second_view is not None
    await interviews_service.book(db_session, second_view, start=slots[0])

    token = create_interview_token(first.id)
    resp = await client.post(
        f"/api/v1/public/interviews/{token}/book", json={"start": slots[0].isoformat()}
    )
    assert resp.status_code == 409
    assert resp.json()["detail"] == "slot-taken"


@pytest.mark.usefixtures("migrated_db", "bucket", "multi_mode")
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

    interview_id = read_interview_token(token)
    row = (
        await db_session.execute(select(Interview.ics_sequence).where(Interview.id == interview_id))
    ).scalar_one()
    assert row == 1  # booked at 0, one reschedule

    cancelled = await client.post(f"/api/v1/public/interviews/{token}/cancel")
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelled"
    # idempotent second cancel
    assert (await client.post(f"/api/v1/public/interviews/{token}/cancel")).status_code == 200
    context = await client.get(f"/api/v1/public/interviews/{token}")
    assert context.json()["status"] == "cancelled"
    assert context.json()["available_slots"] == []


async def test_bad_token_404s(client: AsyncClient) -> None:
    resp = await client.get("/api/v1/public/interviews/garbage")
    assert resp.status_code == 404


@pytest.mark.usefixtures("migrated_db")
async def test_lock_timeout_fails_fast_as_lock_busy(monkeypatch: pytest.MonkeyPatch) -> None:
    """M5.7 H4: a hung lock holder must produce a fast retryable error, not
    park every waiter."""
    monkeypatch.setattr(interviews_service, "LOCK_TIMEOUT_MS", 150)
    interviewer_id = uuid.uuid4()
    engine = create_async_engine(settings.database_url, poolclass=NullPool)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with factory() as holder, holder.begin():
            await interviews_service._lock_interviewer(holder, interviewer_id)
            async with factory() as waiter, waiter.begin():
                with pytest.raises(interviews_service.LockBusyError):
                    await interviews_service._lock_interviewer(waiter, interviewer_id)
    finally:
        await engine.dispose()


@pytest.mark.usefixtures("migrated_db", "bucket", "multi_mode")
async def test_book_sets_sequence_zero_and_reschedule_increments(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    token, slots = await _booking_token(client, db_session, monkeypatch)
    interview_id = read_interview_token(token)

    async def sequence() -> int:
        value = (
            await db_session.execute(
                select(Interview.ics_sequence).where(Interview.id == interview_id)
            )
        ).scalar_one()
        return int(value)

    assert (
        await client.post(f"/api/v1/public/interviews/{token}/book", json={"start": slots[0]})
    ).status_code == 200
    assert await sequence() == 0
    # non-overlapping targets: a 45-minute booking blocks the next 30-minute grid slot
    for expected, slot in ((1, slots[2]), (2, slots[4])):
        moved = await client.post(
            f"/api/v1/public/interviews/{token}/reschedule", json={"start": slot}
        )
        assert moved.status_code == 200, moved.text
        assert await sequence() == expected


async def _outbox_rows(db_session: AsyncSession, interview_id: object) -> list[EmailOutbox]:
    application_id = (
        await db_session.execute(
            select(Interview.application_id).where(Interview.id == interview_id)
        )
    ).scalar_one()
    return list(
        (
            await db_session.execute(
                select(EmailOutbox)
                .where(EmailOutbox.application_id == application_id)
                .order_by(EmailOutbox.created_at, EmailOutbox.kind)
            )
        )
        .scalars()
        .all()
    )


@pytest.mark.usefixtures("migrated_db", "bucket", "multi_mode")
async def test_book_queues_confirmation_and_interviewer_invite(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    token, slots = await _booking_token(client, db_session, monkeypatch)
    interview_id = read_interview_token(token)
    assert (
        await client.post(f"/api/v1/public/interviews/{token}/book", json={"start": slots[0]})
    ).status_code == 200
    rows = {row.kind: row for row in await _outbox_rows(db_session, interview_id)}
    assert {"interview_invite", "interview_confirmed", "interview_scheduled"} <= set(rows)
    confirmed = rows["interview_confirmed"].payload
    scheduled = rows["interview_scheduled"].payload
    assert confirmed["to"].startswith("cand-")
    assert scheduled["to"].startswith("admin-")
    assert confirmed["uid"] == scheduled["uid"] == f"interview-{interview_id}@ganek"
    assert confirmed["sequence"] == scheduled["sequence"] == 0
    assert confirmed["rescheduled"] is False
    # a fresh signed token (timestamped), so decode instead of comparing bytes
    mailed_token = str(confirmed["booking_url"]).rsplit("/", 1)[-1]
    assert read_interview_token(mailed_token) == interview_id
    assert scheduled["applicant_url"].endswith(f"/admin/applicants?selected={confirmed['ref']}")
    assert confirmed["start"] == {
        "$dt": datetime.fromisoformat(slots[0]).astimezone(UTC).isoformat()
    }


@pytest.mark.usefixtures("migrated_db", "bucket", "multi_mode")
async def test_reschedule_queues_both_with_sequence_one(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    token, slots = await _booking_token(client, db_session, monkeypatch)
    interview_id = read_interview_token(token)
    assert (
        await client.post(f"/api/v1/public/interviews/{token}/book", json={"start": slots[0]})
    ).status_code == 200
    assert (
        await client.post(f"/api/v1/public/interviews/{token}/reschedule", json={"start": slots[2]})
    ).status_code == 200
    rows = await _outbox_rows(db_session, interview_id)
    moved = [row for row in rows if row.payload.get("rescheduled") is True]
    assert sorted(row.kind for row in moved) == ["interview_confirmed", "interview_scheduled"]
    assert all(row.payload["sequence"] == 1 for row in moved)


@pytest.mark.usefixtures("migrated_db", "bucket", "multi_mode")
async def test_candidate_cancel_booked_mails_interviewer_only(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    token, slots = await _booking_token(client, db_session, monkeypatch)
    interview_id = read_interview_token(token)
    assert (
        await client.post(f"/api/v1/public/interviews/{token}/book", json={"start": slots[0]})
    ).status_code == 200
    before = len(await _outbox_rows(db_session, interview_id))
    assert (await client.post(f"/api/v1/public/interviews/{token}/cancel")).status_code == 200
    rows = await _outbox_rows(db_session, interview_id)
    assert len(rows) == before + 1
    assert rows[-1].kind == "interview_cancelled_interviewer"
    assert rows[-1].payload["cancelled_by"] == "The candidate"
    assert rows[-1].payload["to"].startswith("admin-")
    assert rows[-1].payload["sequence"] == 1


@pytest.mark.usefixtures("migrated_db", "bucket", "multi_mode")
async def test_candidate_cancel_pending_mails_nobody(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    token, _ = await _booking_token(client, db_session, monkeypatch)
    interview_id = read_interview_token(token)
    before = len(await _outbox_rows(db_session, interview_id))
    assert (await client.post(f"/api/v1/public/interviews/{token}/cancel")).status_code == 200
    assert len(await _outbox_rows(db_session, interview_id)) == before


@pytest.mark.usefixtures("migrated_db", "bucket", "multi_mode")
async def test_sequences_stay_monotonic(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    token, slots = await _booking_token(client, db_session, monkeypatch)
    interview_id = read_interview_token(token)
    base = f"/api/v1/public/interviews/{token}"
    assert (await client.post(f"{base}/book", json={"start": slots[0]})).status_code == 200
    assert (await client.post(f"{base}/reschedule", json={"start": slots[2]})).status_code == 200
    assert (await client.post(f"{base}/reschedule", json={"start": slots[4]})).status_code == 200
    assert (await client.post(f"{base}/cancel")).status_code == 200
    rows = [row for row in await _outbox_rows(db_session, interview_id) if "uid" in row.payload]
    uids = {row.payload["uid"] for row in rows}
    assert uids == {f"interview-{interview_id}@ganek"}
    by_kind: dict[str, list[int]] = {}
    for row in rows:
        by_kind.setdefault(row.kind, []).append(int(row.payload["sequence"]))
    assert by_kind["interview_confirmed"] == [0, 1, 2]
    assert by_kind["interview_scheduled"] == [0, 1, 2]
    assert by_kind["interview_cancelled_interviewer"] == [3]


@pytest.mark.usefixtures("migrated_db", "bucket", "multi_mode")
async def test_invite_ics_download_when_booked(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    token, slots = await _booking_token(client, db_session, monkeypatch)
    interview_id = read_interview_token(token)
    assert (
        await client.post(f"/api/v1/public/interviews/{token}/book", json={"start": slots[0]})
    ).status_code == 200
    resp = await client.get(f"/api/v1/public/interviews/{token}/invite.ics")
    assert resp.status_code == 200, resp.text
    assert resp.headers["content-type"].startswith("text/calendar")
    assert resp.headers["content-disposition"] == 'attachment; filename="interview.ics"'
    lines = resp.text.replace("\r\n ", "").split("\r\n")
    assert "METHOD:PUBLISH" in lines
    assert f"UID:interview-{interview_id}@ganek" in lines
    assert "SEQUENCE:0" in lines
    assert any(line.startswith("ATTENDEE;CN=Marta Vidal") for line in lines)


@pytest.mark.usefixtures("migrated_db", "bucket", "multi_mode")
async def test_invite_ics_409_when_pending(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    token, _ = await _booking_token(client, db_session, monkeypatch)
    resp = await client.get(f"/api/v1/public/interviews/{token}/invite.ics")
    assert resp.status_code == 409
    assert resp.json()["detail"] == "not-booked"


async def test_invite_ics_404_bad_token(client: AsyncClient) -> None:
    resp = await client.get("/api/v1/public/interviews/garbage/invite.ics")
    assert resp.status_code == 404
