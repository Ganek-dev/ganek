"""RFC 5545 renderer for interview invites (pure, no DB)."""

import uuid
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from app.services import ics

BERLIN = ZoneInfo("Europe/Berlin")
INTERVIEW_ID = uuid.UUID("12345678-1234-5678-1234-567812345678")


def _event(**overrides: object) -> ics.CalendarEvent:
    start = datetime(2026, 11, 16, 10, 0, tzinfo=BERLIN)
    base: dict[str, object] = {
        "uid": ics.interview_uid(INTERVIEW_ID),
        "sequence": 0,
        "start": start,
        "end": start + timedelta(minutes=45),
        "summary": "Hiring manager interview - Backend Engineer at Acme",
        "description": "Your work, our stack.",
        "location": "Room 2",
        "organizer_email": "no-reply@acme.example",
        "organizer_name": "Acme",
        "attendees": (("Jane Applicant", "jane@example.com"), ("Erika", "erika@acme.example")),
        "url": "https://jobs.acme.example/interview/tok",
    }
    base.update(overrides)
    return ics.CalendarEvent(**base)  # type: ignore[arg-type]


def _lines(rendered: str) -> list[str]:
    """Logical content lines: unfolded, so long ATTENDEE lines compare whole."""
    assert rendered.endswith("\r\n")
    return rendered.replace("\r\n ", "")[:-2].split("\r\n")


def test_request_has_required_properties() -> None:
    lines = _lines(ics.render(_event(), method="REQUEST"))
    assert lines[0] == "BEGIN:VCALENDAR"
    assert lines[-1] == "END:VCALENDAR"
    assert "VERSION:2.0" in lines
    assert "PRODID:-//Ganek//Interview scheduling//EN" in lines
    assert "METHOD:REQUEST" in lines
    assert f"UID:interview-{INTERVIEW_ID}@ganek" in lines
    assert "SEQUENCE:0" in lines
    assert "DTSTART:20261116T090000Z" in lines
    assert "DTEND:20261116T094500Z" in lines
    assert "SUMMARY:Hiring manager interview - Backend Engineer at Acme" in lines
    assert "LOCATION:Room 2" in lines
    assert "URL:https://jobs.acme.example/interview/tok" in lines
    assert "ORGANIZER;CN=Acme:mailto:no-reply@acme.example" in lines
    assert (
        "ATTENDEE;CN=Jane Applicant;ROLE=REQ-PARTICIPANT;PARTSTAT=NEEDS-ACTION;RSVP=FALSE:"
        "mailto:jane@example.com"
    ) in lines
    assert (
        "ATTENDEE;CN=Erika;ROLE=REQ-PARTICIPANT;PARTSTAT=NEEDS-ACTION;RSVP=FALSE:"
        "mailto:erika@acme.example"
    ) in lines
    assert "STATUS:CONFIRMED" in lines
    assert any(line.startswith("DTSTAMP:") and line.endswith("Z") for line in lines)


def test_cancel_status_and_sequence() -> None:
    lines = _lines(ics.render(_event(sequence=3), method="CANCEL"))
    assert "METHOD:CANCEL" in lines
    assert "STATUS:CANCELLED" in lines
    assert "SEQUENCE:3" in lines
    assert "STATUS:CONFIRMED" not in lines


def test_publish_has_no_status_cancelled() -> None:
    lines = _lines(ics.render(_event(), method="PUBLISH"))
    assert "METHOD:PUBLISH" in lines
    assert "STATUS:CONFIRMED" in lines


def test_text_escaping() -> None:
    lines = _lines(ics.render(_event(description="a, b; c\\d\nnext"), method="REQUEST"))
    assert "DESCRIPTION:a\\, b\\; c\\\\d\\nnext" in lines


def test_folding_counts_octets() -> None:
    description = "ä" * 120  # two octets each; 240 octets of content
    rendered = ics.render(_event(description=description), method="REQUEST")
    physical = rendered[:-2].split("\r\n")
    assert all(len(line.encode()) <= 75 for line in physical)
    continuations = [line for line in physical if line.startswith(" ")]
    assert len(continuations) >= 3
    unfolded = rendered.replace("\r\n ", "")
    assert f"DESCRIPTION:{description}\r\n" in unfolded


def test_dst_boundary_is_utc_instant() -> None:
    start = datetime(2026, 3, 29, 3, 0, tzinfo=BERLIN)  # clocks jumped 02:00 -> 03:00
    lines = _lines(
        ics.render(_event(start=start, end=start + timedelta(minutes=30)), method="REQUEST")
    )
    assert "DTSTART:20260329T010000Z" in lines
    assert "DTEND:20260329T013000Z" in lines


def test_naive_datetime_rejected() -> None:
    naive = datetime(2026, 11, 16, 10, 0)
    with pytest.raises(ValueError):
        ics.render(_event(start=naive, end=naive + timedelta(minutes=30)), method="REQUEST")


def test_location_and_url_omitted_when_empty() -> None:
    lines = _lines(ics.render(_event(location="", url=None), method="REQUEST"))
    assert not any(line.startswith("LOCATION") for line in lines)
    assert not any(line.startswith("URL") for line in lines)


def test_dtstamp_uses_given_now() -> None:
    now = datetime(2026, 10, 31, 12, 0, tzinfo=UTC)
    lines = _lines(ics.render(_event(), method="REQUEST", now=now))
    assert "DTSTAMP:20261031T120000Z" in lines
