"""Suppression list end to end (board card A7): the provider webhook adds
addresses, the outbox skips them, and the trail shows it."""

import base64
import smtplib
from email.message import EmailMessage
from typing import Any
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import settings
from app.models import Company, EmailOutbox, EmailStatus, EmailSuppression
from app.services import outbox as outbox_service
from app.services import suppression
from tests.db import database_reachable

pytestmark = pytest.mark.skipif(
    not database_reachable(), reason="database not reachable (start postgres or use CI)"
)

SECRET = "whsec-test"
WEBHOOK = "/api/v1/email/webhooks/mailjet"


def _basic(user: str, password: str) -> dict[str, str]:
    return {"Authorization": "Basic " + base64.b64encode(f"{user}:{password}".encode()).decode()}


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


@pytest.fixture
def webhook_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "email_webhook_secret", SECRET)


@pytest.fixture
def smtp_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    FakeSMTP.sent = []
    monkeypatch.setattr(settings, "email_provider", "smtp")
    monkeypatch.setattr(settings, "smtp_host", "mail.example.com")
    monkeypatch.setattr(smtplib, "SMTP", FakeSMTP)


@pytest.fixture
async def ctx() -> Any:
    engine = create_async_engine(settings.database_url, poolclass=NullPool)
    yield {"session_factory": async_sessionmaker(engine, expire_on_commit=False)}
    await engine.dispose()


async def _company(db: AsyncSession) -> Company:
    company = Company(slug=f"sup-{uuid4().hex[:8]}", name="Suppress Co", settings={})
    db.add(company)
    await db.flush()
    return company


async def _queued(db: AsyncSession, company: Company, to: str) -> EmailOutbox:
    row = EmailOutbox(
        company_id=company.id,
        kind="application_received",
        payload=outbox_service._serialize(
            {
                "to": to,
                "ref": "r-1",
                "candidate_name": "Jane",
                "job_title": "Role",
                "company_name": company.name,
            }
        ),
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row


async def _fresh(db: AsyncSession, row_id: Any) -> EmailOutbox:
    db.expire_all()
    return (await db.execute(select(EmailOutbox).where(EmailOutbox.id == row_id))).scalar_one()


# --- webhook authentication ---------------------------------------------------


async def test_webhook_rejects_unsigned_and_wrong_secret(
    client: AsyncClient, webhook_on: None
) -> None:
    event = {"event": "spam", "email": "a@ganek-ci.dev"}
    unsigned = await client.post(WEBHOOK, json=event)
    assert unsigned.status_code == 401
    assert unsigned.headers["www-authenticate"].startswith("Basic")
    wrong = await client.post(WEBHOOK, json=event, headers=_basic("ganek", "nope"))
    assert wrong.status_code == 401
    garbage = await client.post(WEBHOOK, json=event, headers={"Authorization": "Basic %%%"})
    assert garbage.status_code == 401


async def test_webhook_is_off_without_a_secret(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "email_webhook_secret", None)
    resp = await client.post(
        WEBHOOK, json={"event": "spam", "email": "a@ganek-ci.dev"}, headers=_basic("ganek", "")
    )
    assert resp.status_code == 401


async def test_webhook_requires_json(client: AsyncClient, webhook_on: None) -> None:
    resp = await client.post(WEBHOOK, content=b"not json", headers=_basic("any-user", SECRET))
    assert resp.status_code == 422


# --- suppression effects ------------------------------------------------------


async def test_signed_hard_bounce_suppresses_and_marks_the_outbox_row(
    client: AsyncClient, db_session: AsyncSession, webhook_on: None
) -> None:
    company = await _company(db_session)
    address = f"bounce-{uuid4().hex[:6]}@ganek-ci.dev"
    row = await _queued(db_session, company, address)
    row.status = EmailStatus.SENT
    await db_session.commit()
    row_id, company_id = row.id, company.id

    resp = await client.post(
        WEBHOOK,
        json=[
            {
                "event": "bounce",
                "email": address.upper(),
                "hard_bounce": True,
                "error": "user unknown",
                "CustomID": str(row_id),
            }
        ],
        headers=_basic("ganek", SECRET),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"received": 1, "suppressed": 1}

    entry = await db_session.get(EmailSuppression, suppression.hash_email(address))
    assert entry is not None
    assert (entry.reason, entry.source, entry.detail) == ("bounce", "mailjet", "user unknown")
    assert entry.company_id == company_id
    fresh = await _fresh(db_session, row_id)
    assert fresh.status is EmailStatus.BOUNCED
    assert fresh.last_error == "user unknown"


async def test_spam_complaint_marks_complained_and_soft_bounce_only_annotates(
    client: AsyncClient, db_session: AsyncSession, webhook_on: None
) -> None:
    company = await _company(db_session)
    spam_to = f"spam-{uuid4().hex[:6]}@ganek-ci.dev"
    soft_to = f"soft-{uuid4().hex[:6]}@ganek-ci.dev"
    spam_row = await _queued(db_session, company, spam_to)
    soft_row = await _queued(db_session, company, soft_to)
    spam_id, soft_id = spam_row.id, soft_row.id

    resp = await client.post(
        WEBHOOK,
        json=[
            {"event": "spam", "email": spam_to, "source": "JMRPP", "CustomID": str(spam_id)},
            {
                "event": "bounce",
                "email": soft_to,
                "hard_bounce": False,
                "error": "mailbox full",
                "CustomID": str(soft_id),
            },
            {"event": "sent", "email": soft_to},  # ignored
        ],
        headers=_basic("ganek", SECRET),
    )
    assert resp.status_code == 200
    assert resp.json() == {"received": 2, "suppressed": 1}

    assert (await _fresh(db_session, spam_id)).status is EmailStatus.COMPLAINED
    soft = await _fresh(db_session, soft_id)
    assert soft.status is EmailStatus.QUEUED
    assert soft.last_error == "soft bounce: mailbox full"
    assert await db_session.get(EmailSuppression, suppression.hash_email(soft_to)) is None


async def test_repeat_event_refreshes_the_entry_and_ignores_bad_custom_ids(
    client: AsyncClient, db_session: AsyncSession, webhook_on: None
) -> None:
    address = f"twice-{uuid4().hex[:6]}@ganek-ci.dev"
    for custom_id, reason in (("not-a-uuid", "spam"), (str(uuid4()), "unsub")):
        resp = await client.post(
            WEBHOOK,
            json={"event": reason, "email": address, "CustomID": custom_id},
            headers=_basic("ganek", SECRET),
        )
        assert resp.status_code == 200, resp.text
    entries = (
        (
            await db_session.execute(
                select(EmailSuppression).where(
                    EmailSuppression.email_hash == suppression.hash_email(address)
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(entries) == 1
    assert entries[0].reason == "unsubscribe"


# --- the outbox honours the list ---------------------------------------------


async def test_worker_skips_suppressed_addresses_without_an_outbound_call(
    db_session: AsyncSession, ctx: Any, smtp_ok: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.worker import deliver_email

    monkeypatch.setattr(outbox_service, "EAGER_DELIVERY_FOR_TESTS", False)
    company = await _company(db_session)
    address = f"skip-{uuid4().hex[:6]}@ganek-ci.dev"
    await suppression.suppress(
        db_session, email=address, reason="bounce", source="mailjet", detail="user unknown"
    )
    row = await _queued(db_session, company, address)
    row_id = row.id

    await deliver_email(ctx, str(row_id))

    fresh = await _fresh(db_session, row_id)
    assert fresh.status is EmailStatus.SUPPRESSED
    assert fresh.attempts == 0
    assert fresh.last_error is not None
    assert fresh.last_error.startswith("address suppressed (bounce on ")
    assert FakeSMTP.sent == []


async def test_worker_still_sends_to_clean_addresses_and_tags_the_row_id(
    db_session: AsyncSession, ctx: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.worker import deliver_email

    monkeypatch.setattr(outbox_service, "EAGER_DELIVERY_FOR_TESTS", False)
    seen: list[str | None] = []
    monkeypatch.setattr(settings, "email_provider", "mailjet")
    monkeypatch.setattr(settings, "mailjet_api_key", "k")
    monkeypatch.setattr(settings, "mailjet_secret_key", "s")
    from app.services import email_providers

    def fake_post(url: str, *, headers: dict[str, str], body: dict[str, Any]) -> dict[str, Any]:
        seen.append(body["Messages"][0].get("CustomID"))
        return {"Messages": [{"Status": "success"}]}

    monkeypatch.setattr(email_providers, "_http_post_json", fake_post)
    company = await _company(db_session)
    row = await _queued(db_session, company, f"clean-{uuid4().hex[:6]}@ganek-ci.dev")
    row_id = row.id

    await deliver_email(ctx, str(row_id))

    assert (await _fresh(db_session, row_id)).status is EmailStatus.SENT
    assert seen == [str(row_id)]


async def test_eager_path_skips_suppressed_addresses(
    db_session: AsyncSession, smtp_ok: None
) -> None:
    company = await _company(db_session)
    address = f"eager-{uuid4().hex[:6]}@ganek-ci.dev"
    await suppression.suppress(db_session, email=address, reason="complaint", source="mailjet")
    row = await outbox_service.queue_email(
        db_session,
        kind="application_received",
        company_id=company.id,
        to=address,
        candidate_name="Jane",
        job_title="Role",
        company_name=company.name,
    )
    assert row.status is EmailStatus.SUPPRESSED
    assert FakeSMTP.sent == []


async def test_trail_exposes_the_new_states(
    client: AsyncClient,
    db_session: AsyncSession,
    webhook_on: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "mode", "multi")  # registration stays open
    creds = {"email": f"admin-{uuid4().hex[:8]}@ganek-ci.dev", "password": "a-long-secure-password"}
    reg = await client.post(
        "/api/v1/auth/register",
        json={"company_name": f"Trail Co {uuid4().hex[:6]}", **creds},
    )
    assert reg.status_code == 201, reg.text
    company_id = UUID((await client.get("/api/v1/auth/me")).json()["company_id"])
    job = await client.post(
        "/api/v1/jobs",
        json={"title": "Role", "description": "d", "location": "Remote", "tags": []},
    )
    assert job.status_code == 201, job.text
    # one outbox row the trail can show, hand-made so no email needs to go out
    from app.models import Application, Candidate

    candidate = Candidate(
        company_id=company_id, name="Jane", email=f"jane-{uuid4().hex[:6]}@ganek-ci.dev"
    )
    db_session.add(candidate)
    await db_session.flush()
    application = Application(
        company_id=company_id,
        job_id=job.json()["id"],
        candidate_id=candidate.id,
        cv_object_key="cvs/none.pdf",
        cv_filename="cv.pdf",
        cv_size=1,
    )
    db_session.add(application)
    await db_session.flush()
    row = EmailOutbox(
        company_id=company_id,
        application_id=application.id,
        kind="quiz_invite",
        payload={"to": candidate.email},
        status=EmailStatus.SENT,
    )
    db_session.add(row)
    await db_session.commit()
    row_id, application_id = row.id, application.id

    resp = await client.post(
        WEBHOOK,
        json={"event": "spam", "email": candidate.email, "CustomID": str(row_id)},
        headers=_basic("ganek", SECRET),
    )
    assert resp.status_code == 200, resp.text
    trail = await client.get(f"/api/v1/applications/{application_id}/emails")
    assert trail.status_code == 200, trail.text
    assert [entry["status"] for entry in trail.json()] == ["complained"]
