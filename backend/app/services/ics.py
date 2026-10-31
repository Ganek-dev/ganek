"""RFC 5545 rendering for interview invites.

One VEVENT per message. The UID is derived from the interview id and stays
the same across the invite (METHOD:REQUEST), every reschedule (REQUEST
with a higher SEQUENCE) and the cancellation (METHOD:CANCEL), which is how
a recipient's calendar knows the three messages describe one event. No
third-party library: the format needed here is a few dozen lines.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

Method = Literal["REQUEST", "CANCEL", "PUBLISH"]

PRODID = "-//Ganek//Interview scheduling//EN"
MAX_LINE_OCTETS = 75


@dataclass(frozen=True)
class CalendarEvent:
    uid: str
    sequence: int
    start: datetime
    end: datetime
    summary: str
    description: str
    location: str
    organizer_email: str
    organizer_name: str
    attendees: tuple[tuple[str, str], ...]  # (display name, email)
    url: str | None = None


def interview_uid(interview_id: uuid.UUID) -> str:
    return f"interview-{interview_id}@ganek"


def escape_text(value: str) -> str:
    """TEXT value escaping: backslash, comma, semicolon and newlines."""
    return (
        value.replace("\\", "\\\\")
        .replace(";", "\\;")
        .replace(",", "\\,")
        .replace("\r\n", "\\n")
        .replace("\n", "\\n")
    )


def fold(line: str) -> str:
    """Fold a content line at 75 octets with CRLF + space continuations,
    never splitting a multi-byte character."""
    encoded = line.encode()
    if len(encoded) <= MAX_LINE_OCTETS:
        return line
    pieces: list[str] = []
    current = ""
    limit = MAX_LINE_OCTETS
    for char in line:
        if len((current + char).encode()) > limit:
            pieces.append(current)
            current = char
            limit = MAX_LINE_OCTETS - 1  # continuation lines carry the leading space
        else:
            current += char
    pieces.append(current)
    return "\r\n ".join(pieces)


def _utc(value: datetime, name: str) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")
    return value.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")


def render(event: CalendarEvent, *, method: Method, now: datetime | None = None) -> str:
    stamp = _utc(now or datetime.now(UTC), "now")
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        f"PRODID:{PRODID}",
        f"METHOD:{method}",
        "BEGIN:VEVENT",
        f"UID:{event.uid}",
        f"SEQUENCE:{event.sequence}",
        f"DTSTAMP:{stamp}",
        f"DTSTART:{_utc(event.start, 'start')}",
        f"DTEND:{_utc(event.end, 'end')}",
        f"SUMMARY:{escape_text(event.summary)}",
        f"DESCRIPTION:{escape_text(event.description)}",
    ]
    if event.location:
        lines.append(f"LOCATION:{escape_text(event.location)}")
    if event.url:
        lines.append(f"URL:{event.url}")
    lines.append(f"ORGANIZER;CN={escape_text(event.organizer_name)}:mailto:{event.organizer_email}")
    for name, email in event.attendees:
        lines.append(
            f"ATTENDEE;CN={escape_text(name)};ROLE=REQ-PARTICIPANT;PARTSTAT=NEEDS-ACTION;"
            f"RSVP=FALSE:mailto:{email}"
        )
    lines.append("STATUS:CANCELLED" if method == "CANCEL" else "STATUS:CONFIRMED")
    lines.extend(["END:VEVENT", "END:VCALENDAR"])
    return "".join(fold(line) + "\r\n" for line in lines)
