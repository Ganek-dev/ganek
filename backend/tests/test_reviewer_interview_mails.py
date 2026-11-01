"""Interview mails to a reviewer-role interviewer: the invite lists the candidate
as an attendee as it does for staff (owner decision 2026-11-01), the links go to
the slim review page. A staff interviewer's mail is unchanged."""

from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any
from uuid import UUID

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import settings
from app.models import Application, Candidate, Company, EmailOutbox, Interview, User, UserRole
from app.services import auth as auth_service
from app.services import email_providers as providers
from app.services import erasure
from app.worker import send_interview_reminder
from tests.db import database_reachable
from tests.test_reviewer_gate import _env
from tests.test_scorecards_api import _login

pytestmark = pytest.mark.skipif(
    not database_reachable(), reason="database not reachable (start postgres or use CI)"
)


@pytest.fixture(autouse=True)
def multi_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "mode", "multi")


@pytest.fixture
def sent(monkeypatch: pytest.MonkeyPatch) -> Iterator[list[providers.OutboundMessage]]:
    captured: list[providers.OutboundMessage] = []

    class Capture:
        name = "capture"

        def configured(self) -> bool:
            return True

        def send(self, message: providers.OutboundMessage) -> None:
            captured.append(message)

    monkeypatch.setattr(settings, "smtp_host", "mail.example.com")
    monkeypatch.setattr(settings, "email_from", "no-reply@acme.example")
    monkeypatch.setattr(providers, "current", lambda: Capture())
    # delivery on must not switch signup to the email-verification flow
    monkeypatch.setattr(auth_service, "verification_required", lambda: False)
    yield captured


@dataclass
class Setup:
    application_id: str
    candidate_email: str
    interviewer_id: str
    interviewer_email: str
    company_id: UUID
    token: str
    slots: list[str]


async def _setup(client: AsyncClient, db: AsyncSession, *, role: str) -> Setup:
    """An interview requested from the given kind of teammate, booking page
    open. ``role`` is "reviewer" or "member" (the staff interviewer)."""
    env = await _env(client, db)
    await _login(client, env.co.admin)
    interviewer_id = env.reviewer_id if role == "reviewer" else env.co.member_id
    interviewer_email = env.reviewer["email"] if role == "reviewer" else env.co.member["email"]
    resp = await client.post(
        f"/api/v1/applications/{env.co.application_id}/interview",
        json={
            "interviewer_user_id": interviewer_id,
            "duration_minutes": 45,
            "timezone": "Europe/Berlin",
            "description": "Your work, our stack.",
        },
    )
    assert resp.status_code == 201, resp.text
    application = await db.get(Application, UUID(env.co.application_id))
    assert application is not None
    candidate = await db.get(Candidate, application.candidate_id)
    assert candidate is not None
    invite = (
        (
            await db.execute(
                select(EmailOutbox).where(
                    EmailOutbox.application_id == application.id,
                    EmailOutbox.kind == "interview_invite",
                )
            )
        )
        .scalars()
        .one()
    )
    token = str(invite.payload["booking_url"]).rsplit("/", 1)[-1]
    context = await client.get(f"/api/v1/public/interviews/{token}")
    assert context.status_code == 200, context.text
    return Setup(
        application_id=env.co.application_id,
        candidate_email=candidate.email,
        interviewer_id=interviewer_id,
        interviewer_email=interviewer_email,
        company_id=application.company_id,
        token=token,
        slots=context.json()["available_slots"],
    )


async def _book(client: AsyncClient, setup: Setup) -> None:
    resp = await client.post(
        f"/api/v1/public/interviews/{setup.token}/book", json={"start": setup.slots[0]}
    )
    assert resp.status_code == 200, resp.text


def _to(sent: list[providers.OutboundMessage], setup: Setup) -> list[providers.OutboundMessage]:
    return [m for m in sent if m.to == setup.interviewer_email]


def _with_calendar(
    sent: list[providers.OutboundMessage], setup: Setup
) -> list[providers.OutboundMessage]:
    return [m for m in _to(sent, setup) if m.calendar is not None]


def _ics_lines(message: providers.OutboundMessage) -> list[str]:
    assert message.calendar is not None
    return message.calendar.content.replace("\r\n ", "")[:-2].split("\r\n")


def _field(lines: list[str], name: str) -> str:
    values = [line.split(":", 1)[1] for line in lines if line.startswith(f"{name}:")]
    assert len(values) == 1, (name, lines)
    return values[0]


def _attendees(lines: list[str]) -> list[str]:
    return [line.rsplit("mailto:", 1)[1] for line in lines if line.startswith("ATTENDEE")]


def _assert_valid_ics(lines: list[str], *, method: str) -> None:
    """RFC 5546: REQUEST and CANCEL both need an organizer and an attendee."""
    assert lines[:2] == ["BEGIN:VCALENDAR", "VERSION:2.0"]
    assert lines[-2:] == ["END:VEVENT", "END:VCALENDAR"]
    assert _field(lines, "METHOD") == method
    assert any(line.startswith("ORGANIZER") for line in lines)
    assert _attendees(lines)


def _assert_message_clean(message: providers.OutboundMessage, setup: Setup) -> None:
    assert setup.candidate_email not in message.subject
    assert setup.candidate_email not in message.text
    assert setup.candidate_email not in (message.html or "")
    if message.calendar is not None:
        assert setup.candidate_email not in message.calendar.content.replace("\r\n ", "")


@pytest.mark.usefixtures("migrated_db", "bucket")
async def test_booking_mail_to_a_reviewer(
    client: AsyncClient, db_session: AsyncSession, sent: list[providers.OutboundMessage]
) -> None:
    setup = await _setup(client, db_session, role="reviewer")
    await _book(client, setup)

    mails = _with_calendar(sent, setup)
    assert len(mails) == 1
    message = mails[0]
    lines = _ics_lines(message)
    _assert_valid_ics(lines, method="REQUEST")
    assert _attendees(lines) == [setup.candidate_email, setup.interviewer_email]
    assert _field(lines, "URL").endswith(f"/review/{setup.application_id}")
    assert f"/review/{setup.application_id}" in message.text
    assert f'/review/{setup.application_id}"' in (message.html or "")
    assert "/admin/" not in message.text + (message.html or "") + "\n".join(lines)
    # the scorecard request that fires with the booking carries no address
    for mail in _to(sent, setup):
        if mail.calendar is None:
            _assert_message_clean(mail, setup)


@pytest.mark.usefixtures("migrated_db", "bucket")
async def test_booking_mail_to_staff_is_unchanged(
    client: AsyncClient, db_session: AsyncSession, sent: list[providers.OutboundMessage]
) -> None:
    setup = await _setup(client, db_session, role="member")
    await _book(client, setup)

    message = _with_calendar(sent, setup)[0]
    lines = _ics_lines(message)
    assert _attendees(lines) == [setup.candidate_email, setup.interviewer_email]
    admin = f"/admin/applicants?selected={setup.application_id}"
    assert _field(lines, "URL").endswith(admin)
    assert admin in message.text
    assert "/review/" not in message.text


@pytest.mark.usefixtures("migrated_db", "bucket")
async def test_reschedule_mail_to_a_reviewer_updates_the_same_event(
    client: AsyncClient, db_session: AsyncSession, sent: list[providers.OutboundMessage]
) -> None:
    setup = await _setup(client, db_session, role="reviewer")
    await _book(client, setup)
    resp = await client.post(
        f"/api/v1/public/interviews/{setup.token}/reschedule", json={"start": setup.slots[-1]}
    )
    assert resp.status_code == 200, resp.text

    first, moved = _with_calendar(sent, setup)
    assert moved.subject.startswith("Interview moved")
    before, after = _ics_lines(first), _ics_lines(moved)
    _assert_valid_ics(after, method="REQUEST")
    assert _field(after, "UID") == _field(before, "UID")
    assert (_field(before, "SEQUENCE"), _field(after, "SEQUENCE")) == ("0", "1")
    assert _attendees(after) == [setup.candidate_email, setup.interviewer_email]
    assert _field(after, "URL").endswith(f"/review/{setup.application_id}")
    assert f"/review/{setup.application_id}" in moved.text


@pytest.mark.usefixtures("migrated_db", "bucket")
async def test_reschedule_mail_to_staff_is_unchanged(
    client: AsyncClient, db_session: AsyncSession, sent: list[providers.OutboundMessage]
) -> None:
    setup = await _setup(client, db_session, role="member")
    await _book(client, setup)
    resp = await client.post(
        f"/api/v1/public/interviews/{setup.token}/reschedule", json={"start": setup.slots[-1]}
    )
    assert resp.status_code == 200, resp.text

    moved = _with_calendar(sent, setup)[-1]
    lines = _ics_lines(moved)
    assert _attendees(lines) == [setup.candidate_email, setup.interviewer_email]
    assert _field(lines, "URL").endswith(f"/admin/applicants?selected={setup.application_id}")


@pytest.mark.usefixtures("migrated_db", "bucket")
@pytest.mark.parametrize("by", ["candidate", "recruiter"])
async def test_cancel_mail_to_a_reviewer(
    client: AsyncClient,
    db_session: AsyncSession,
    sent: list[providers.OutboundMessage],
    by: str,
) -> None:
    setup = await _setup(client, db_session, role="reviewer")
    await _book(client, setup)
    if by == "candidate":
        resp = await client.post(f"/api/v1/public/interviews/{setup.token}/cancel")
    else:
        resp = await client.post(f"/api/v1/applications/{setup.application_id}/interview/cancel")
    assert resp.status_code == 200, resp.text

    invite, cancel = _with_calendar(sent, setup)
    lines = _ics_lines(cancel)
    _assert_valid_ics(lines, method="CANCEL")
    assert _field(lines, "UID") == _field(_ics_lines(invite), "UID")
    assert _field(lines, "SEQUENCE") == "1"
    assert _attendees(lines) == [setup.candidate_email, setup.interviewer_email]
    # the cancellation carries no link for anybody: nothing to open any more
    assert not [line for line in lines if line.startswith("URL")]
    assert "/admin/" not in cancel.text + (cancel.html or "")


@pytest.mark.usefixtures("migrated_db", "bucket")
@pytest.mark.parametrize("by", ["candidate", "recruiter"])
async def test_cancel_mail_to_staff_is_unchanged(
    client: AsyncClient,
    db_session: AsyncSession,
    sent: list[providers.OutboundMessage],
    by: str,
) -> None:
    setup = await _setup(client, db_session, role="member")
    await _book(client, setup)
    if by == "candidate":
        resp = await client.post(f"/api/v1/public/interviews/{setup.token}/cancel")
    else:
        resp = await client.post(f"/api/v1/applications/{setup.application_id}/interview/cancel")
    assert resp.status_code == 200, resp.text

    cancel = _with_calendar(sent, setup)[-1]
    assert _attendees(_ics_lines(cancel)) == [setup.candidate_email, setup.interviewer_email]


@pytest.mark.usefixtures("migrated_db", "bucket")
async def test_teammate_demoted_after_the_booking_can_still_cancel_the_event(
    client: AsyncClient, db_session: AsyncSession, sent: list[providers.OutboundMessage]
) -> None:
    """The role decides at send time; the event in their calendar still goes."""
    setup = await _setup(client, db_session, role="member")
    await _book(client, setup)
    teammate = await db_session.get(User, UUID(setup.interviewer_id))
    assert teammate is not None
    teammate.role = UserRole.REVIEWER
    await db_session.commit()

    resp = await client.post(f"/api/v1/public/interviews/{setup.token}/cancel")
    assert resp.status_code == 200, resp.text

    invite, cancel = _with_calendar(sent, setup)
    lines = _ics_lines(cancel)
    _assert_valid_ics(lines, method="CANCEL")
    assert _field(lines, "UID") == _field(_ics_lines(invite), "UID")
    assert _attendees(lines) == [setup.candidate_email, setup.interviewer_email]


@pytest.mark.usefixtures("migrated_db", "bucket")
@pytest.mark.parametrize("role", ["reviewer", "member"])
async def test_erasure_notice_never_names_the_candidate(
    client: AsyncClient,
    db_session: AsyncSession,
    sent: list[providers.OutboundMessage],
    role: str,
) -> None:
    setup = await _setup(client, db_session, role=role)
    await _book(client, setup)
    application = await db_session.get(Application, UUID(setup.application_id))
    company = await db_session.get(Company, setup.company_id)
    assert application is not None and company is not None
    summary = await erasure.erase_candidate(
        db_session, company, application.candidate_id, actor_user_id=None
    )
    assert summary is not None and summary.cancel_notices == 1

    notice = _with_calendar(sent, setup)[-1]
    lines = _ics_lines(notice)
    _assert_valid_ics(lines, method="CANCEL")
    assert _attendees(lines) == [setup.interviewer_email]
    assert "/admin/" not in notice.text + (notice.html or "")
    _assert_message_clean(notice, setup)


async def _run_reminder(db: AsyncSession, setup: Setup) -> None:
    interview = (
        await db.execute(
            select(Interview).where(Interview.application_id == UUID(setup.application_id))
        )
    ).scalar_one()
    await db.refresh(interview)
    assert interview.scheduled_start is not None
    engine = create_async_engine(settings.database_url, poolclass=NullPool)
    ctx: dict[str, Any] = {"session_factory": async_sessionmaker(engine, expire_on_commit=False)}
    try:
        await send_interview_reminder(ctx, str(interview.id), interview.scheduled_start.isoformat())
    finally:
        await engine.dispose()


@pytest.mark.usefixtures("migrated_db", "bucket")
async def test_reminder_mail_to_a_reviewer(
    client: AsyncClient, db_session: AsyncSession, sent: list[providers.OutboundMessage]
) -> None:
    setup = await _setup(client, db_session, role="reviewer")
    await _book(client, setup)
    await _run_reminder(db_session, setup)

    reminder = [m for m in _to(sent, setup) if m.subject.startswith("Reminder:")]
    assert len(reminder) == 1
    assert reminder[0].calendar is None
    assert f"/review/{setup.application_id}" in reminder[0].text
    assert f'/review/{setup.application_id}"' in (reminder[0].html or "")
    assert "/admin/" not in reminder[0].text + (reminder[0].html or "")
    _assert_message_clean(reminder[0], setup)


@pytest.mark.usefixtures("migrated_db", "bucket")
async def test_reminder_mail_to_staff_is_unchanged(
    client: AsyncClient, db_session: AsyncSession, sent: list[providers.OutboundMessage]
) -> None:
    setup = await _setup(client, db_session, role="member")
    await _book(client, setup)
    await _run_reminder(db_session, setup)

    reminder = [m for m in _to(sent, setup) if m.subject.startswith("Reminder:")]
    assert f"/admin/applicants?selected={setup.application_id}" in reminder[0].text
    assert "/review/" not in reminder[0].text
