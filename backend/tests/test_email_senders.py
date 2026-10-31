"""Interview mails that carry a calendar part (pure: the provider is faked)."""

from datetime import UTC, datetime

import pytest

from app.core.config import settings
from app.services import email as email_service
from app.services import email_providers as providers

START = datetime(2026, 11, 16, 9, 0, tzinfo=UTC)


@pytest.fixture
def sent(monkeypatch: pytest.MonkeyPatch) -> list[providers.OutboundMessage]:
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
    return captured


def _confirmed(**overrides: object) -> None:
    kwargs: dict[str, object] = {
        "to": "jane@example.com",
        "ref": "app-1",
        "candidate_name": "Jane Applicant",
        "interviewer_name": "Erika",
        "job_title": "Backend Engineer",
        "company_name": "Acme",
        "title": "Hiring manager interview",
        "description": "Your work, our stack.",
        "start": START,
        "duration_minutes": 45,
        "timezone": "Europe/Berlin",
        "location": "https://teams.example/room-2",
        "uid": "interview-abc@ganek",
        "sequence": 0,
        "booking_url": "https://jobs.acme.example/interview/tok",
        "interviewer_email": "erika@acme.example",
        "rescheduled": False,
        "brand_primary": None,
    }
    kwargs.update(overrides)
    email_service.send_interview_confirmed(**kwargs)  # type: ignore[arg-type]


def _scheduled(**overrides: object) -> None:
    kwargs: dict[str, object] = {
        "to": "erika@acme.example",
        "ref": "app-1",
        "candidate_name": "Jane Applicant",
        "candidate_email": "jane@example.com",
        "interviewer_name": "Erika",
        "job_title": "Backend Engineer",
        "company_name": "Acme",
        "title": "Hiring manager interview",
        "description": "",
        "start": START,
        "duration_minutes": 45,
        "timezone": "Europe/Berlin",
        "location": "Room 2",
        "uid": "interview-abc@ganek",
        "sequence": 2,
        "applicant_url": "https://jobs.acme.example/admin/applicants?selected=app-1",
        "rescheduled": True,
    }
    kwargs.update(overrides)
    email_service.send_interview_scheduled(**kwargs)  # type: ignore[arg-type]


def _ics_lines(message: providers.OutboundMessage) -> list[str]:
    assert message.calendar is not None
    return message.calendar.content.replace("\r\n ", "")[:-2].split("\r\n")


def test_interview_confirmed_carries_request_part(sent: list[providers.OutboundMessage]) -> None:
    _confirmed()
    message = sent[0]
    assert message.subject == "Confirmed: your interview for Backend Engineer at Acme"
    assert "Mon, Nov 16 · 10:00" in message.text  # Europe/Berlin
    assert "https://teams.example/room-2" in message.text
    assert "https://jobs.acme.example/interview/tok" in message.text
    assert message.calendar is not None
    assert message.calendar.method == "REQUEST"
    lines = _ics_lines(message)
    assert "UID:interview-abc@ganek" in lines
    assert "SEQUENCE:0" in lines
    assert "SUMMARY:Hiring manager interview - Backend Engineer at Acme" in lines
    assert "LOCATION:https://teams.example/room-2" in lines
    assert "URL:https://jobs.acme.example/interview/tok" in lines
    assert "DTSTART:20261116T090000Z" in lines
    assert "DTEND:20261116T094500Z" in lines
    assert any(line.startswith("ATTENDEE;CN=Jane Applicant") for line in lines)
    assert any(line.startswith("ATTENDEE;CN=Erika") for line in lines)
    assert "DESCRIPTION:Your work\\, our stack.\\nLocation: https://teams.example/room-2" in lines


def test_interview_confirmed_rescheduled_subject(sent: list[providers.OutboundMessage]) -> None:
    _confirmed(rescheduled=True, sequence=1, location="")
    message = sent[0]
    assert message.subject == "Rescheduled: your interview for Backend Engineer at Acme"
    lines = _ics_lines(message)
    assert "SEQUENCE:1" in lines
    assert not any(line.startswith("LOCATION") for line in lines)


def test_interview_scheduled_summary_names_candidate(sent: list[providers.OutboundMessage]) -> None:
    _scheduled()
    message = sent[0]
    assert message.subject == "Interview moved: Jane Applicant - Backend Engineer"
    assert "Room 2" in message.text
    assert "https://jobs.acme.example/admin/applicants?selected=app-1" in message.text
    lines = _ics_lines(message)
    assert "SUMMARY:Hiring manager interview - Jane Applicant (Backend Engineer)" in lines
    assert "URL:https://jobs.acme.example/admin/applicants?selected=app-1" in lines
    assert "SEQUENCE:2" in lines
    assert message.calendar is not None and message.calendar.method == "REQUEST"


def test_interview_scheduled_first_booking_subject(sent: list[providers.OutboundMessage]) -> None:
    _scheduled(rescheduled=False, sequence=0)
    assert sent[0].subject == "Interview booked: Jane Applicant - Backend Engineer"


def test_organizer_from_display_email_from(
    sent: list[providers.OutboundMessage], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "email_from", "Ganek <no-reply@x.dev>")
    _confirmed()
    assert "ORGANIZER;CN=Acme:mailto:no-reply@x.dev" in _ics_lines(sent[0])


def test_interview_invite_copy_mentions_both_sides(sent: list[providers.OutboundMessage]) -> None:
    email_service.send_interview_invite(
        to="jane@example.com",
        candidate_name="Jane",
        job_title="Backend Engineer",
        company_name="Acme",
        duration_minutes=45,
        booking_url="https://jobs.acme.example/interview/tok",
        brand_primary=None,
    )
    message = sent[0]
    flat_text = " ".join(message.text.split())  # the plain body wraps at 72 columns
    assert "you and your interviewer both receive a calendar invite" in flat_text
    assert message.html is not None
    assert "you and your interviewer both receive a calendar invite" in message.html
    assert "meeting link" not in flat_text
    assert message.calendar is None
