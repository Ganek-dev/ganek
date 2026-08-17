"""Email outbox (M5.7 H4): queue-then-deliver with retry, sweep, and the
admin surfaces. The conftest eager mode is switched OFF here — these tests
exercise the real worker path.
"""

import smtplib
from datetime import UTC, datetime, timedelta
from email.message import EmailMessage
from typing import Any
from uuid import uuid4

import pytest
from arq import Retry
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import settings
from app.models import Company, EmailOutbox, EmailStatus
from app.services import outbox as outbox_service
from tests.db import database_reachable

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


async def _queued(db: AsyncSession, company: Company, **overrides: object) -> EmailOutbox:
    fields: dict[str, object] = {
        "company_id": company.id,
        "kind": "application_received",
        "payload": outbox_service._serialize(
            {
                "to": "jane@vetd-ci.dev",
                "ref": "r-1",
                "candidate_name": "Jane",
                "job_title": "Role",
                "company_name": company.name,
            }
        ),
    }
    fields.update(overrides)
    row = EmailOutbox(**fields)
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row


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
    assert FakeSMTP.sent[0]["To"] == "jane@vetd-ci.dev"


@pytest.mark.usefixtures("migrated_db", "real_outbox", "smtp_ok")
async def test_deliver_noops_on_non_queued_rows(db_session: AsyncSession, ctx: Any) -> None:
    from app.worker import deliver_email

    company = await _company(db_session)
    row = await _queued(db_session, company, status=EmailStatus.SENT)
    await deliver_email(ctx, str(row.id))
    assert FakeSMTP.sent == []


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

    # third strike parks the row — no Retry raised, arq is done with it
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
    assert fresh.last_error == "SMTP not configured"


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
    assert "jane@vetd-ci.dev" not in caplog.text
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
    assert fresh is not None  # young queued row — must not be swept yet

    stuck = await outbox_service.stuck_rows(
        db_session, older_than=datetime.now(UTC) - timedelta(minutes=5)
    )
    assert old_id in stuck
    assert done_id not in stuck
    assert fresh.id not in stuck


@pytest.mark.usefixtures("migrated_db", "bucket")
async def test_purge_sweeps_terminal_outbox_rows(db_session: AsyncSession) -> None:
    from app.services import retention

    company = await _company(db_session)
    company_id = company.id  # plain value before expire_all (async lazy-refresh trap)
    old_sent = await _queued(db_session, company, status=EmailStatus.SENT)
    old_failed = await _queued(db_session, company, status=EmailStatus.FAILED)
    old_queued = await _queued(db_session, company)  # never swept by age alone
    young_sent = await _queued(db_session, company, status=EmailStatus.SENT)
    ids = {
        "old_sent": old_sent.id,
        "old_failed": old_failed.id,
        "old_queued": old_queued.id,
        "young_sent": young_sent.id,
    }
    await db_session.execute(
        EmailOutbox.__table__.update()
        .where(EmailOutbox.id.in_([ids["old_sent"], ids["old_failed"], ids["old_queued"]]))
        .values(created_at=datetime.now(UTC) - timedelta(days=31))
    )
    await db_session.commit()

    summary = await retention.run_purge(db_session, now=datetime.now(UTC))
    assert summary.emails >= 2

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
    assert remaining == {ids["old_queued"], ids["young_sent"]}


PDF_BYTES = b"%PDF-1.4 outbox flow"


async def _apply_flow(client: AsyncClient) -> tuple[str, str]:
    """Register + publish + apply (no assessment). Ends logged in as admin;
    returns (application_id, candidate_email)."""
    import httpx

    creds = {"email": f"admin-{uuid4().hex[:8]}@vetd-ci.dev", "password": "a-long-secure-password"}
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
    async with httpx.AsyncClient() as raw:
        put = await raw.put(
            ticket["upload_url"],
            content=PDF_BYTES,
            headers={"Content-Type": ticket["content_type"]},
        )
        assert put.status_code == 200
    email = f"cand-{uuid4().hex[:8]}@vetd-ci.dev"
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
    signup verification (H4 item 12) — out of scope for outbox tests."""
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
        "email": f"other-{uuid4().hex[:8]}@vetd-ci.dev",
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
    creds = {"email": f"admin-{uuid4().hex[:8]}@vetd-ci.dev", "password": "a-long-secure-password"}
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
    assert "SMTP send failed" in resp.json()["detail"]
