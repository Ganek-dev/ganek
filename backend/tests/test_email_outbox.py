"""Email outbox (M5.7 H4): queue-then-deliver with retry, sweep, and the
admin surfaces. The conftest eager mode is switched OFF here - these tests
exercise the real worker path.
"""

import smtplib
from datetime import UTC, datetime, timedelta
from email.message import EmailMessage
from typing import Any
from uuid import UUID, uuid4

import pytest
from arq import Retry
from httpx import AsyncClient
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core import queue
from app.core.config import settings
from app.models import Application, ApplicationStage, Company, EmailOutbox, EmailStatus
from app.services import outbox as outbox_service
from tests.db import database_reachable
from tests.helpers import upload_pdf

pytestmark = pytest.mark.skipif(
    not database_reachable(), reason="database not reachable (start postgres or use CI)"
)


class FakeSMTP:
    sent: list[EmailMessage] = []

    def __init__(self, host: str, port: int, timeout: int) -> None: ...

    def __enter__(self) -> "FakeSMTP":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def starttls(self) -> None: ...

    def login(self, user: str, password: str) -> None: ...

    def send_message(self, message: EmailMessage) -> None:
        FakeSMTP.sent.append(message)


class ExplodingSMTP(FakeSMTP):
    def send_message(self, message: EmailMessage) -> None:
        raise smtplib.SMTPException("boom")


@pytest.fixture
def real_outbox(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(outbox_service, "EAGER_DELIVERY_FOR_TESTS", False)


@pytest.fixture
def smtp_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    FakeSMTP.sent = []
    monkeypatch.setattr(settings, "smtp_host", "mail.example.com")
    monkeypatch.setattr(smtplib, "SMTP", FakeSMTP)


@pytest.fixture
async def ctx() -> Any:
    engine = create_async_engine(settings.database_url, poolclass=NullPool)
    yield {"session_factory": async_sessionmaker(engine, expire_on_commit=False)}
    await engine.dispose()


async def _company(db: AsyncSession) -> Company:
    company = Company(slug=f"ob-{uuid4().hex[:8]}", name="Outbox Co", settings={})
    db.add(company)
    await db.flush()
    return company


async def _queued(
    db: AsyncSession,
    company: Company,
    send_after: datetime | None = None,
    **overrides: object,
) -> EmailOutbox:
    fields: dict[str, object] = {
        "company_id": company.id,
        "kind": "application_received",
        "payload": outbox_service._serialize(
            {
                "to": "jane@ganek-ci.dev",
                "ref": "r-1",
                "candidate_name": "Jane",
                "job_title": "Role",
                "company_name": company.name,
            }
        ),
    }
    if send_after is not None:
        fields["send_after"] = send_after
    fields.update(overrides)
    row = EmailOutbox(**fields)
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row


def test_scheduled_and_cancelled_fit_the_status_column() -> None:
    assert EmailStatus.SCHEDULED.value == "scheduled"
    assert EmailStatus.CANCELLED.value == "cancelled"
    assert max(len(s.value) for s in EmailStatus) <= 10
    row = EmailOutbox(kind="rejection", payload={})
    assert row.send_after is None and row.cancelled_at is None


def test_payload_roundtrips_datetimes() -> None:
    when = datetime(2026, 8, 17, 12, 30, tzinfo=UTC)
    packed = outbox_service._serialize({"expires_at": when, "n": 3, "s": "x", "none": None})
    assert packed["expires_at"] == {"$dt": "2026-08-17T12:30:00+00:00"}
    assert outbox_service._deserialize(packed) == {
        "expires_at": when,
        "n": 3,
        "s": "x",
        "none": None,
    }


@pytest.mark.usefixtures("migrated_db", "real_outbox", "smtp_ok")
async def test_deliver_sends_and_marks_row(db_session: AsyncSession, ctx: Any) -> None:
    from app.worker import deliver_email

    company = await _company(db_session)
    row = await _queued(db_session, company)
    row_id = row.id  # plain value before expire_all (async lazy-refresh trap)
    await deliver_email(ctx, str(row_id))

    db_session.expire_all()
    fresh = (
        await db_session.execute(select(EmailOutbox).where(EmailOutbox.id == row_id))
    ).scalar_one()
    assert fresh.status is EmailStatus.SENT
    assert fresh.attempts == 1
    assert fresh.sent_at is not None
    assert len(FakeSMTP.sent) == 1
    assert FakeSMTP.sent[0]["To"] == "jane@ganek-ci.dev"


@pytest.mark.usefixtures("migrated_db", "real_outbox", "smtp_ok")
async def test_deliver_noops_on_non_queued_rows(db_session: AsyncSession, ctx: Any) -> None:
    from app.worker import deliver_email

    company = await _company(db_session)
    row = await _queued(db_session, company, status=EmailStatus.SENT)
    await deliver_email(ctx, str(row.id))
    assert FakeSMTP.sent == []


@pytest.mark.usefixtures("migrated_db", "real_outbox", "smtp_ok")
async def test_deliver_noops_on_a_cancelled_row(db_session: AsyncSession, ctx: Any) -> None:
    from app.worker import deliver_email

    company = await _company(db_session)
    row = await _queued(
        db_session,
        company,
        status=EmailStatus.CANCELLED,
        send_after=datetime.now(UTC) - timedelta(minutes=1),
    )
    row_id = row.id
    await deliver_email(ctx, str(row_id))
    fresh = await _fresh(db_session, row_id)
    assert FakeSMTP.sent == []
    assert fresh.status is EmailStatus.CANCELLED
    assert fresh.attempts == 0


@pytest.mark.usefixtures("migrated_db")
async def test_queue_with_send_after_writes_scheduled_and_defers(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[dict[str, Any]] = []

    async def fake_enqueue(function: str, *args: str, **kw: Any) -> bool:
        calls.append({"function": function, "args": args, **kw})
        return True

    monkeypatch.setattr(queue, "enqueue", fake_enqueue)
    monkeypatch.setattr(outbox_service, "EAGER_DELIVERY_FOR_TESTS", True)
    when = datetime.now(UTC) + timedelta(days=1)
    company = await _company(db_session)
    row = await outbox_service.queue_email(
        db_session,
        kind="rejection",
        company_id=company.id,
        send_after=when,
        to="jane@ganek-ci.dev",
        ref="r-1",
        candidate_name="Jane Applicant",
        job_title="Backend Engineer",
        company_name=company.name,
        careers_url="https://jobs.example/outbox-co",
        completed_assessment=False,
    )
    assert row is not None
    assert row.status is EmailStatus.SCHEDULED
    assert row.send_after == when
    assert row.sent_at is None
    assert calls == [
        {
            "function": "deliver_email",
            "args": (str(row.id),),
            "defer_until": when,
            "job_id": f"email-{row.id}",
        }
    ]


@pytest.mark.usefixtures("migrated_db", "real_outbox", "smtp_ok")
async def test_deliver_never_sends_a_scheduled_row_early(
    db_session: AsyncSession, ctx: Any
) -> None:
    from app.worker import deliver_email

    company = await _company(db_session)
    row = await _queued(
        db_session,
        company,
        status=EmailStatus.SCHEDULED,
        send_after=datetime.now(UTC) + timedelta(hours=1),
    )
    row_id = row.id
    await deliver_email(ctx, str(row_id))
    fresh = await _fresh(db_session, row_id)
    assert FakeSMTP.sent == []
    assert fresh.status is EmailStatus.SCHEDULED
    assert fresh.attempts == 0


@pytest.mark.usefixtures("migrated_db", "real_outbox", "smtp_ok")
async def test_deliver_releases_a_due_scheduled_row(db_session: AsyncSession, ctx: Any) -> None:
    from app.worker import deliver_email

    company = await _company(db_session)
    row = await _queued(
        db_session,
        company,
        kind="rejection",
        payload=_rejection_payload(company),
        status=EmailStatus.SCHEDULED,
        send_after=datetime.now(UTC) - timedelta(minutes=1),
    )
    row_id = row.id
    await deliver_email(ctx, str(row_id))
    fresh = await _fresh(db_session, row_id)
    assert len(FakeSMTP.sent) == 1
    assert fresh.status is EmailStatus.SENT
    assert fresh.sent_at is not None
    assert fresh.rendered_subject == "Your application to Outbox Co"


async def _scheduled_rejection_for(
    client: AsyncClient, db: AsyncSession, stage: ApplicationStage
) -> EmailOutbox:
    """A due scheduled rejection row on a real application moved to `stage`."""
    app_id, _ = await _apply_flow(client)
    application = (
        await db.execute(select(Application).where(Application.id == UUID(app_id)))
    ).scalar_one()
    application.stage = stage
    await db.commit()
    company = await db.get(Company, application.company_id)
    assert company is not None
    return await _queued(
        db,
        company,
        kind="rejection",
        payload=_rejection_payload(company),
        status=EmailStatus.SCHEDULED,
        send_after=datetime.now(UTC) - timedelta(minutes=1),
        application_id=application.id,
    )


_FLOW = ("migrated_db", "bucket", "multi_mode", "real_outbox", "smtp_ok", "no_verification")


@pytest.mark.usefixtures(*_FLOW)
async def test_deliver_cancels_a_due_rejection_whose_application_is_not_rejected(
    client: AsyncClient, db_session: AsyncSession, ctx: Any
) -> None:
    from app.worker import deliver_email

    row = await _scheduled_rejection_for(client, db_session, ApplicationStage.SCREENING)
    row_id = row.id
    await deliver_email(ctx, str(row_id))
    fresh = await _fresh(db_session, row_id)
    assert FakeSMTP.sent == []
    assert fresh.status is EmailStatus.CANCELLED
    assert fresh.cancelled_at is not None


@pytest.mark.usefixtures(*_FLOW)
async def test_deliver_releases_a_due_rejection_whose_application_is_rejected(
    client: AsyncClient, db_session: AsyncSession, ctx: Any
) -> None:
    from app.worker import deliver_email

    row = await _scheduled_rejection_for(client, db_session, ApplicationStage.REJECTED)
    row_id = row.id
    await deliver_email(ctx, str(row_id))
    fresh = await _fresh(db_session, row_id)
    assert len(FakeSMTP.sent) == 1
    assert fresh.status is EmailStatus.SENT


async def _held_rejection_after_one_failure(
    client: AsyncClient,
    db: AsyncSession,
    ctx: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[UUID, UUID]:
    """A held rejection released by the worker whose first send failed: the
    row is `queued`, attempts=1, send_after set. Returns (row id, app id)."""
    from app.worker import deliver_email

    row = await _scheduled_rejection_for(client, db, ApplicationStage.REJECTED)
    row_id, app_id = row.id, row.application_id
    assert app_id is not None
    monkeypatch.setattr(smtplib, "SMTP", ExplodingSMTP)
    with pytest.raises(Retry):
        await deliver_email(ctx, str(row_id))
    monkeypatch.setattr(smtplib, "SMTP", FakeSMTP)
    fresh = await _fresh(db, row_id)
    assert fresh.status is EmailStatus.QUEUED
    assert fresh.attempts == 1
    return row_id, app_id


@pytest.mark.usefixtures(*_FLOW)
async def test_retry_cancels_a_held_rejection_whose_application_is_not_rejected(
    client: AsyncClient,
    db_session: AsyncSession,
    ctx: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.worker import deliver_email

    row_id, app_id = await _held_rejection_after_one_failure(client, db_session, ctx, monkeypatch)
    # a direct write: the guard itself is under test, not the route's cancel
    await db_session.execute(
        update(Application).where(Application.id == app_id).values(stage=ApplicationStage.SCREENING)
    )
    await db_session.commit()

    await deliver_email(ctx, str(row_id))
    fresh = await _fresh(db_session, row_id)
    assert FakeSMTP.sent == []
    assert fresh.status is EmailStatus.CANCELLED
    assert fresh.cancelled_at is not None
    assert fresh.attempts == 1


@pytest.mark.usefixtures(*_FLOW)
async def test_retry_still_sends_a_held_rejection_on_a_rejected_application(
    client: AsyncClient,
    db_session: AsyncSession,
    ctx: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.worker import deliver_email

    row_id, _ = await _held_rejection_after_one_failure(client, db_session, ctx, monkeypatch)
    await deliver_email(ctx, str(row_id))
    fresh = await _fresh(db_session, row_id)
    assert len(FakeSMTP.sent) == 1
    assert fresh.status is EmailStatus.SENT


@pytest.mark.usefixtures(*_FLOW)
async def test_unreject_cancels_a_released_hold_but_the_staff_route_stays_scheduled_only(
    client: AsyncClient,
    db_session: AsyncSession,
    ctx: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.worker import deliver_email

    row_id, app_id = await _held_rejection_after_one_failure(client, db_session, ctx, monkeypatch)
    resp = await client.post(f"/api/v1/applications/{app_id}/emails/{row_id}/cancel")
    assert resp.status_code == 409
    assert (await _fresh(db_session, row_id)).status is EmailStatus.QUEUED

    resp = await client.patch(
        f"/api/v1/applications/{app_id}/stage",
        json={"stage": "screening", "notify_candidate": False},
    )
    assert resp.status_code == 200, resp.text
    assert (await _fresh(db_session, row_id)).status is EmailStatus.CANCELLED

    await deliver_email(ctx, str(row_id))
    assert FakeSMTP.sent == []


@pytest.mark.usefixtures(*_FLOW)
async def test_a_rejection_queued_immediately_is_untouched_by_the_hold_rules(
    client: AsyncClient, db_session: AsyncSession, ctx: Any
) -> None:
    from app.worker import deliver_email

    held = await _scheduled_rejection_for(client, db_session, ApplicationStage.REJECTED)
    held_id, app_id = held.id, held.application_id
    company_id = held.company_id
    company = await db_session.get(Company, company_id)
    assert company is not None
    immediate = await _queued(
        db_session,
        company,
        kind="rejection",
        payload=_rejection_payload(company),
        application_id=app_id,
    )
    immediate_id = immediate.id

    # the un-reject takes the held row and leaves the immediate one queued
    resp = await client.patch(
        f"/api/v1/applications/{app_id}/stage",
        json={"stage": "screening", "notify_candidate": False},
    )
    assert resp.status_code == 200, resp.text
    assert (await _fresh(db_session, held_id)).status is EmailStatus.CANCELLED
    assert (await _fresh(db_session, immediate_id)).status is EmailStatus.QUEUED

    # and the worker sends it although the application is no longer rejected
    await deliver_email(ctx, str(immediate_id))
    assert len(FakeSMTP.sent) == 1
    assert (await _fresh(db_session, immediate_id)).status is EmailStatus.SENT


@pytest.mark.usefixtures("migrated_db")
async def test_due_scheduled_rows_ignores_future_and_other_statuses(
    db_session: AsyncSession,
) -> None:
    company = await _company(db_session)
    now = datetime.now(UTC)
    due = await _queued(
        db_session, company, status=EmailStatus.SCHEDULED, send_after=now - timedelta(minutes=10)
    )
    future = await _queued(
        db_session, company, status=EmailStatus.SCHEDULED, send_after=now + timedelta(hours=1)
    )
    queued = await _queued(db_session, company, send_after=now - timedelta(minutes=10))
    got = await outbox_service.due_scheduled_rows(db_session, before=now)
    assert due.id in got
    assert future.id not in got
    assert queued.id not in got


class _FakeRedis:
    def __init__(self) -> None:
        self.jobs: list[tuple[Any, ...]] = []
        self.kwargs: list[dict[str, Any]] = []

    async def enqueue_job(self, *args: Any, **kw: Any) -> None:
        self.jobs.append(args)
        self.kwargs.append(kw)


@pytest.mark.usefixtures("migrated_db")
async def test_sweep_enqueues_only_scheduled_rows_overdue_by_five_minutes(
    db_session: AsyncSession, ctx: Any
) -> None:
    from app.worker import sweep_outbox

    company = await _company(db_session)
    now = datetime.now(UTC)
    future = await _queued(
        db_session, company, status=EmailStatus.SCHEDULED, send_after=now + timedelta(hours=1)
    )
    barely = await _queued(
        db_session, company, status=EmailStatus.SCHEDULED, send_after=now - timedelta(minutes=1)
    )
    overdue = await _queued(
        db_session, company, status=EmailStatus.SCHEDULED, send_after=now - timedelta(minutes=30)
    )
    ids = {str(future.id), str(barely.id), str(overdue.id)}
    redis = _FakeRedis()
    await sweep_outbox({**ctx, "redis": redis})
    enqueued = {args[1] for args in redis.jobs if args[0] == "deliver_email"} & ids
    assert enqueued == {str(overdue.id)}
    # no job_id: the original `email-{id}` job may still hold the key
    assert all("_job_id" not in kw and "job_id" not in kw for kw in redis.kwargs)


@pytest.mark.usefixtures("migrated_db", "real_outbox")
async def test_deliver_retries_then_parks_as_failed(
    db_session: AsyncSession, ctx: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.worker import deliver_email

    monkeypatch.setattr(settings, "smtp_host", "mail.example.com")
    monkeypatch.setattr(smtplib, "SMTP", ExplodingSMTP)
    company = await _company(db_session)
    row = await _queued(db_session, company)
    row_id = row.id  # plain value before expire_all (async lazy-refresh trap)

    for attempt in (1, 2):
        with pytest.raises(Retry):
            await deliver_email(ctx, str(row_id))
        db_session.expire_all()
        fresh = (
            await db_session.execute(select(EmailOutbox).where(EmailOutbox.id == row_id))
        ).scalar_one()
        assert fresh.status is EmailStatus.QUEUED
        assert fresh.attempts == attempt
        assert "boom" in (fresh.last_error or "")

    # third strike parks the row - no Retry raised, arq is done with it
    await deliver_email(ctx, str(row_id))
    db_session.expire_all()
    fresh = (
        await db_session.execute(select(EmailOutbox).where(EmailOutbox.id == row_id))
    ).scalar_one()
    assert fresh.status is EmailStatus.FAILED
    assert fresh.attempts == outbox_service.MAX_ATTEMPTS


@pytest.mark.usefixtures("migrated_db", "real_outbox")
async def test_deliver_fails_immediately_without_smtp(
    db_session: AsyncSession, ctx: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.worker import deliver_email

    monkeypatch.setattr(settings, "smtp_host", None)
    company = await _company(db_session)
    row = await _queued(db_session, company)
    row_id = row.id  # plain value before expire_all (async lazy-refresh trap)
    await deliver_email(ctx, str(row_id))  # no Retry: waiting won't configure SMTP
    db_session.expire_all()
    fresh = (
        await db_session.execute(select(EmailOutbox).where(EmailOutbox.id == row_id))
    ).scalar_one()
    assert fresh.status is EmailStatus.FAILED
    assert fresh.last_error == "Email not configured"


@pytest.mark.usefixtures("migrated_db", "real_outbox")
async def test_failure_log_carries_row_id_never_the_address(
    db_session: AsyncSession,
    ctx: Any,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The G4 no-recipients-in-logs guarantee, relocated to the worker."""
    import logging

    from app.worker import deliver_email

    monkeypatch.setattr(settings, "smtp_host", "mail.example.com")
    monkeypatch.setattr(smtplib, "SMTP", ExplodingSMTP)
    company = await _company(db_session)
    row = await _queued(db_session, company)
    row.attempts = outbox_service.MAX_ATTEMPTS - 1  # next failure is terminal
    await db_session.commit()

    with caplog.at_level(logging.WARNING, logger="app.worker"):
        await deliver_email(ctx, str(row.id))
    assert "jane@ganek-ci.dev" not in caplog.text
    assert str(row.id) in caplog.text


@pytest.mark.usefixtures("migrated_db")
async def test_stuck_rows_finds_only_old_queued(db_session: AsyncSession) -> None:
    company = await _company(db_session)
    old = await _queued(db_session, company)
    fresh = await _queued(db_session, company)
    done = await _queued(db_session, company, status=EmailStatus.SENT)
    old_id, done_id = old.id, done.id
    await db_session.execute(
        EmailOutbox.__table__.update()
        .where(EmailOutbox.id.in_([old_id, done_id]))
        .values(created_at=datetime.now(UTC) - timedelta(minutes=30))
    )
    await db_session.commit()
    assert fresh is not None  # young queued row - must not be swept yet

    stuck = await outbox_service.stuck_rows(
        db_session, older_than=datetime.now(UTC) - timedelta(minutes=5)
    )
    assert old_id in stuck
    assert done_id not in stuck
    assert fresh.id not in stuck


@pytest.mark.usefixtures("migrated_db")
async def test_stuck_rows_counts_a_released_row_from_its_send_time(
    db_session: AsyncSession,
) -> None:
    company = await _company(db_session)
    now = datetime.now(UTC)
    released = await _queued(
        db_session, company, send_after=now - timedelta(seconds=30), attempts=1
    )
    overdue = await _queued(db_session, company, send_after=now - timedelta(minutes=30))
    plain = await _queued(db_session, company)
    released_id, overdue_id, plain_id = released.id, overdue.id, plain.id
    # all created long ago, as a row held for days is
    await db_session.execute(
        EmailOutbox.__table__.update()
        .where(EmailOutbox.id.in_([released_id, overdue_id, plain_id]))
        .values(created_at=now - timedelta(days=3))
    )
    await db_session.commit()

    stuck = await outbox_service.stuck_rows(db_session, older_than=now - timedelta(minutes=5))
    assert released_id not in stuck  # its backoff is still running
    assert overdue_id in stuck
    assert plain_id in stuck  # no send_after: still measured from created_at


@pytest.mark.usefixtures("migrated_db", "bucket")
async def test_purge_sweeps_terminal_outbox_rows(db_session: AsyncSession) -> None:
    from app.services import retention

    company = await _company(db_session)
    company_id = company.id  # plain value before expire_all (async lazy-refresh trap)
    old_sent = await _queued(db_session, company, status=EmailStatus.SENT)
    old_failed = await _queued(db_session, company, status=EmailStatus.FAILED)
    old_queued = await _queued(db_session, company)  # never swept by age alone
    young_sent = await _queued(db_session, company, status=EmailStatus.SENT)
    old_cancelled = await _queued(db_session, company, status=EmailStatus.CANCELLED)
    old_scheduled = await _queued(
        db_session,
        company,
        status=EmailStatus.SCHEDULED,
        send_after=datetime.now(UTC) + timedelta(days=1),
    )  # a held mail is never swept by age alone
    ids = {
        "old_sent": old_sent.id,
        "old_failed": old_failed.id,
        "old_queued": old_queued.id,
        "young_sent": young_sent.id,
        "old_cancelled": old_cancelled.id,
        "old_scheduled": old_scheduled.id,
    }
    await db_session.execute(
        EmailOutbox.__table__.update()
        .where(EmailOutbox.id.in_([v for k, v in ids.items() if k.startswith("old_")]))
        .values(created_at=datetime.now(UTC) - timedelta(days=31))
    )
    await db_session.commit()

    summary = await retention.run_purge(db_session, now=datetime.now(UTC))
    assert summary.emails >= 3

    db_session.expire_all()
    remaining = set(
        (
            await db_session.execute(
                select(EmailOutbox.id).where(EmailOutbox.company_id == company_id)
            )
        )
        .scalars()
        .all()
    )
    assert remaining == {ids["old_queued"], ids["young_sent"], ids["old_scheduled"]}


PDF_BYTES = b"%PDF-1.4 outbox flow"


async def _apply_flow(client: AsyncClient) -> tuple[str, str]:
    """Register + publish + apply (no assessment). Ends logged in as admin;
    returns (application_id, candidate_email)."""

    creds = {"email": f"admin-{uuid4().hex[:8]}@ganek-ci.dev", "password": "a-long-secure-password"}
    name = f"Outbox Api Co {uuid4().hex[:6]}"
    assert (
        await client.post("/api/v1/auth/register", json={"company_name": name, **creds})
    ).status_code == 201
    slug = name.lower().replace(" ", "-")
    job = (await client.post("/api/v1/jobs", json={"title": "Role"})).json()
    assert (await client.post(f"/api/v1/jobs/{job['id']}/publish")).status_code == 200
    await client.post("/api/v1/auth/logout")

    base = f"/api/v1/public/companies/{slug}/jobs/{job['slug']}"
    ticket = (await client.post(f"{base}/apply/upload-url")).json()
    assert (await upload_pdf(ticket, PDF_BYTES)).is_success
    email = f"cand-{uuid4().hex[:8]}@ganek-ci.dev"
    resp = await client.post(
        f"{base}/apply",
        json={
            "name": "Olive Applicant",
            "email": email,
            "cv_object_key": ticket["object_key"],
            "cv_filename": "olive.pdf",
        },
    )
    assert resp.status_code == 201, resp.text
    assert (await client.post("/api/v1/auth/login", json=creds)).status_code == 200
    app_id = (await client.get("/api/v1/applications")).json()["items"][0]["id"]
    return app_id, email


@pytest.fixture
def multi_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "mode", "multi")


@pytest.fixture
def no_verification(monkeypatch: pytest.MonkeyPatch) -> None:
    """These flows have SMTP patched in, which would trigger multi-mode
    signup verification (H4 item 12) - out of scope for outbox tests."""
    from app.services import auth as auth_service

    monkeypatch.setattr(auth_service, "verification_required", lambda: False)


@pytest.mark.usefixtures("migrated_db", "bucket", "multi_mode", "smtp_ok", "no_verification")
async def test_apply_writes_outbox_and_panel_surfaces_it(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    app_id, _ = await _apply_flow(client)

    rows = (await client.get(f"/api/v1/applications/{app_id}/emails")).json()
    assert len(rows) == 1
    assert rows[0]["kind"] == "application_received"
    assert rows[0]["status"] == "sent"  # eager test mode delivered inline
    assert "payload" not in rows[0]  # stored kwargs (capability URLs) stay server-side

    # tenant-scoped like every application subresource
    other = {
        "email": f"other-{uuid4().hex[:8]}@ganek-ci.dev",
        "password": "a-long-secure-password",
    }
    assert (
        await client.post(
            "/api/v1/auth/register",
            json={"company_name": f"Other Ob Co {uuid4().hex[:6]}", **other},
        )
    ).status_code == 201
    assert (await client.get(f"/api/v1/applications/{app_id}/emails")).status_code == 404


@pytest.mark.usefixtures("migrated_db", "bucket", "multi_mode", "smtp_ok", "no_verification")
async def test_erasure_takes_outbox_rows_with_the_candidate(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    app_id, _ = await _apply_flow(client)
    assert (await client.post(f"/api/v1/applications/{app_id}/erase-candidate")).status_code == 200
    db_session.expire_all()
    left = (
        (
            await db_session.execute(
                select(EmailOutbox.id).where(EmailOutbox.application_id == app_id)
            )
        )
        .scalars()
        .all()
    )
    assert left == []


@pytest.mark.usefixtures("migrated_db", "bucket", "multi_mode")
async def test_test_email_endpoint(client: AsyncClient, monkeypatch: pytest.MonkeyPatch) -> None:
    creds = {"email": f"admin-{uuid4().hex[:8]}@ganek-ci.dev", "password": "a-long-secure-password"}
    assert (
        await client.post(
            "/api/v1/auth/register",
            json={"company_name": f"Test Mail Co {uuid4().hex[:6]}", **creds},
        )
    ).status_code == 201

    monkeypatch.setattr(settings, "smtp_host", None)
    assert (await client.get("/api/v1/company")).json()["smtp_configured"] is False
    assert (await client.post("/api/v1/company/test-email")).status_code == 409

    FakeSMTP.sent = []
    monkeypatch.setattr(settings, "smtp_host", "mail.example.com")
    monkeypatch.setattr(smtplib, "SMTP", FakeSMTP)
    assert (await client.get("/api/v1/company")).json()["smtp_configured"] is True
    resp = await client.post("/api/v1/company/test-email")
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"sent": True}
    assert len(FakeSMTP.sent) == 1
    assert FakeSMTP.sent[0]["To"] == creds["email"]

    monkeypatch.setattr(smtplib, "SMTP", ExplodingSMTP)
    resp = await client.post("/api/v1/company/test-email")
    assert resp.status_code == 502
    assert "Email send failed" in resp.json()["detail"]


def _rejection_payload(company: Company) -> dict[str, object]:
    """The kwargs ``send_rejection`` takes, as the stage route queues them."""
    return outbox_service._serialize(
        {
            "to": "jane@ganek-ci.dev",
            "ref": "r-1",
            "candidate_name": "Jane Applicant",
            "job_title": "Backend Engineer",
            "company_name": company.name,
            "careers_url": "https://jobs.example/outbox-co",
            "completed_assessment": False,
            "controller_name": None,
            "privacy_url": None,
        }
    )


async def _fresh(db: AsyncSession, row_id: object) -> EmailOutbox:
    db.expire_all()
    return (await db.execute(select(EmailOutbox).where(EmailOutbox.id == row_id))).scalar_one()


@pytest.mark.usefixtures("migrated_db", "real_outbox", "smtp_ok")
async def test_delivery_stores_the_rendered_subject_and_text(
    db_session: AsyncSession, ctx: Any
) -> None:
    from app.worker import deliver_email

    company = await _company(db_session)
    row = await _queued(db_session, company, kind="rejection", payload=_rejection_payload(company))
    row_id = row.id
    await deliver_email(ctx, str(row_id))

    fresh = await _fresh(db_session, row_id)
    assert fresh.status is EmailStatus.SENT
    assert fresh.rendered_subject == "Your application to Outbox Co"
    assert fresh.rendered_text is not None
    assert fresh.rendered_text.startswith("Thank you, Jane Applicant")
    assert "See open positions: https://jobs.example/outbox-co" in fresh.rendered_text
    mime = FakeSMTP.sent[0]
    assert mime["Subject"] == fresh.rendered_subject
    plain = mime.get_body(preferencelist=("plain",))
    assert plain is not None
    assert plain.get_content().rstrip("\n") == fresh.rendered_text.rstrip("\n")


@pytest.mark.usefixtures("migrated_db", "real_outbox")
async def test_dispatch_stores_the_rendering_even_when_transport_fails(
    db_session: AsyncSession, ctx: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.worker import deliver_email

    monkeypatch.setattr(settings, "smtp_host", "mail.example.com")
    monkeypatch.setattr(smtplib, "SMTP", ExplodingSMTP)
    company = await _company(db_session)
    row = await _queued(db_session, company, kind="rejection", payload=_rejection_payload(company))
    row_id = row.id
    with pytest.raises(Retry):
        await deliver_email(ctx, str(row_id))

    fresh = await _fresh(db_session, row_id)
    assert fresh.status is EmailStatus.QUEUED
    assert fresh.attempts == 1
    assert "boom" in (fresh.last_error or "")
    # the timeline shows what was attempted next to "failed"
    assert fresh.rendered_subject == "Your application to Outbox Co"
    assert fresh.rendered_text is not None and "Thank you, Jane Applicant" in fresh.rendered_text


@pytest.mark.usefixtures("migrated_db", "real_outbox")
async def test_unconfigured_instance_still_records_nothing_before_the_sender(
    db_session: AsyncSession, ctx: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Documents the current behaviour: deliver_email parks the row as
    "Email not configured" BEFORE dispatch, so nothing was rendered."""
    from app.worker import deliver_email

    monkeypatch.setattr(settings, "smtp_host", None)
    company = await _company(db_session)
    row = await _queued(db_session, company, kind="rejection", payload=_rejection_payload(company))
    row_id = row.id
    await deliver_email(ctx, str(row_id))

    fresh = await _fresh(db_session, row_id)
    assert fresh.status is EmailStatus.FAILED
    assert fresh.last_error == "Email not configured"
    assert fresh.rendered_subject is None and fresh.rendered_text is None


@pytest.mark.usefixtures("migrated_db", "real_outbox", "smtp_ok")
async def test_stored_text_masks_the_candidate_links_but_the_mail_keeps_them(
    db_session: AsyncSession, ctx: Any
) -> None:
    """The row's text is for recruiters: the candidate's signed quiz and
    status links are masked with the preview placeholder, while the mail
    itself carries the real link."""
    from app.worker import deliver_email

    company = await _company(db_session)
    payload = outbox_service._serialize(
        {
            "to": "jane@ganek-ci.dev",
            "ref": "r-1",
            "candidate_name": "Jane Applicant",
            "job_title": "Backend Engineer",
            "company_name": company.name,
            "brand_primary": None,
            "quiz_url": "https://jobs.example/quiz/tok-secret-123",
            "expires_at": datetime.now(UTC) + timedelta(days=2),
            "days_left": 2,
            "controller_name": None,
            "privacy_url": None,
        }
    )
    row = await _queued(db_session, company, kind="quiz_reminder", payload=payload)
    row_id = row.id
    await deliver_email(ctx, str(row_id))

    fresh = await _fresh(db_session, row_id)
    assert fresh.rendered_text is not None
    assert "https://jobs.example/quiz/personal-link" in fresh.rendered_text
    assert "tok-secret-123" not in fresh.rendered_text
    plain = FakeSMTP.sent[0].get_body(preferencelist=("plain",))
    assert plain is not None and "https://jobs.example/quiz/tok-secret-123" in plain.get_content()
