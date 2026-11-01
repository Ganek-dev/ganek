"""Interview scheduling (single-round v1).

Slots are always computed live from the interviewer's saved availability
(``effective_availability``) minus Ganek's own booked interviews - never
frozen on the interview row. Booking re-checks the chosen slot against the
live slot set under a per-interviewer lock. No calendar connection is
involved: the invite travels as an .ics in Ganek's own mails (the routes
queue them after the booking commits).
"""

import hashlib
import logging
import uuid
from datetime import UTC, datetime, time, timedelta
from email.utils import parseaddr
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core import queue, urls
from app.core.config import settings
from app.models import Application, Company, Interview, InterviewStatus, User
from app.services import activity, ics
from app.services import scorecards as scorecards_service

logger = logging.getLogger(__name__)

SLOT_GRID_MINUTES = 30
HORIZON_DAYS = 14  # slots offered over the next two weeks, starting tomorrow
MAX_INTERVIEW_MINUTES = 60  # schemas.interviews.InterviewCreate caps duration here
WEEKDAY_KEYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
DAY_LABELS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
DEFAULT_AVAILABILITY = {
    day: {"start": "09:00", "end": "17:00"} for day in ("mon", "tue", "wed", "thu", "fri")
}


def effective_availability(user: User) -> tuple[str | None, dict[str, tuple[time, time]]]:
    """(saved timezone or None, per-day windows). Malformed saved days are skipped."""
    saved = user.interview_availability
    tz = saved.get("timezone") if isinstance(saved, dict) else None
    raw = saved.get("days") if isinstance(saved, dict) else DEFAULT_AVAILABILITY
    if not isinstance(raw, dict):
        raw = {}
    windows: dict[str, tuple[time, time]] = {}
    for day, window in raw.items():
        if day not in WEEKDAY_KEYS or not isinstance(window, dict):
            continue
        try:
            start = time.fromisoformat(window["start"])
            end = time.fromisoformat(window["end"])
        except (KeyError, TypeError, ValueError):
            continue
        if start < end:
            windows[day] = (start, end)
    return (tz if isinstance(tz, str) else None), windows


def summarize_availability(windows: dict[str, tuple[time, time]]) -> str:
    """Compact human summary, compressing runs of identical windows: "Mon-Fri 09:00-17:00"."""
    if not windows:
        return "no hours set"
    runs: list[tuple[int, int, tuple[time, time]]] = []
    for index, key in enumerate(WEEKDAY_KEYS):
        window = windows.get(key)
        if window is None:
            continue
        if runs and runs[-1][1] == index - 1 and runs[-1][2] == window:
            runs[-1] = (runs[-1][0], index, window)
        else:
            runs.append((index, index, window))
    parts = []
    for first, last, (start, end) in runs:
        label = DAY_LABELS[first] if first == last else f"{DAY_LABELS[first]}-{DAY_LABELS[last]}"
        parts.append(f"{label} {start:%H:%M}-{end:%H:%M}")
    return " · ".join(parts)


def candidate_event(
    interview: Interview, company: Company, *, booking_url: str
) -> ics.CalendarEvent:
    """The candidate's copy of a booked interview as a calendar event (the
    .ics download on the booking page). Mirrors what the confirmation mail
    carries: same UID and sequence, so adding the file twice is harmless."""
    assert interview.scheduled_start is not None
    candidate = interview.application.candidate
    interviewer = interview.interviewer
    description = "\n".join(
        part
        for part in (
            interview.description,
            f"Location: {interview.location}" if interview.location else "",
        )
        if part
    )
    return ics.CalendarEvent(
        uid=ics.interview_uid(interview.id),
        sequence=interview.ics_sequence,
        start=interview.scheduled_start,
        end=interview.scheduled_start + timedelta(minutes=interview.duration_minutes),
        summary=f"{interview.title} - {interview.application.job.title} at {company.name}",
        description=description,
        location=interview.location,
        organizer_email=parseaddr(settings.email_from)[1] or settings.email_from,
        organizer_name=company.name,
        attendees=(
            (candidate.name, candidate.email),
            (interviewer.display_label, interviewer.email),
        ),
        url=booking_url,
    )


def cancel_notice_fields(interview: Interview) -> dict[str, object]:
    """Calendar fields for the METHOD:CANCEL mails: the event as it was
    sent, one sequence higher. Empty when no time was ever booked (a
    pending request has nothing to remove from a calendar)."""
    if interview.scheduled_start is None:
        return {}
    return {
        "title": interview.title,
        "start": interview.scheduled_start,
        "duration_minutes": interview.duration_minutes,
        "timezone": interview.timezone,
        "location": interview.location,
        "uid": ics.interview_uid(interview.id),
        "sequence": interview.ics_sequence + 1,
    }


def applicant_url_for_interviewer(
    company: Company, interviewer: User, application_id: object
) -> str:
    """Where an interviewer's mail links: a reviewer-role user cannot open the
    admin list and gets the review page."""
    if scorecards_service.is_reviewer_role(interviewer):
        return urls.scorecard_url(company, application_id, reviewer=True)
    return urls.admin_applicant_url(company, application_id)


class InterviewExistsError(Exception):
    """The application already has a pending or booked interview."""


class AlreadyBookedError(Exception):
    """Booking attempted on an interview that already has a time."""


class NotBookedError(Exception):
    """Reschedule attempted before any slot was booked."""


LOCK_TIMEOUT_MS = 8000  # tests shrink this to force the timeout path


class LockBusyError(Exception):
    """The per-interviewer booking lock stayed contended past the timeout."""


class SlotUnavailableError(Exception):
    """The chosen slot is not offered, already past, or just got taken."""


async def _booked_windows(
    db: AsyncSession, interviewer_id: uuid.UUID, window_start: datetime, window_end: datetime
) -> list[tuple[datetime, datetime]]:
    """Busy windows from Ganek's own BOOKED interviews for this interviewer."""
    rows = (
        (
            await db.execute(
                select(Interview).where(
                    Interview.interviewer_user_id == interviewer_id,
                    Interview.status == InterviewStatus.BOOKED,
                    Interview.scheduled_start.is_not(None),
                    Interview.scheduled_start >= window_start,
                    Interview.scheduled_start < window_end,
                )
            )
        )
        .scalars()
        .all()
    )
    windows: list[tuple[datetime, datetime]] = []
    for row in rows:
        start = row.scheduled_start
        if start is None:  # excluded by the query already; narrows for mypy
            continue
        windows.append((start, start + timedelta(minutes=row.duration_minutes)))
    return windows


async def generate_slots(
    db: AsyncSession,
    interviewer: User,
    *,
    duration_minutes: int,
    timezone: str,
) -> list[datetime]:
    """Free 30-min-grid starts over the next HORIZON_DAYS, from the
    interviewer's saved weekly availability (default Mon-Fri 09:00-17:00).
    `timezone` is the fallback zone when the schedule has none saved.

    Raises ValueError for an unknown IANA zone.
    """
    saved_tz, windows = effective_availability(interviewer)
    try:
        zone = ZoneInfo(saved_tz or timezone)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ValueError(f"unknown timezone {saved_tz or timezone!r}") from exc

    now = datetime.now(zone)
    min_start = now + timedelta(hours=1)  # spec §3: at least an hour of lead time
    first_day = now.date() + timedelta(days=1)
    window_start = datetime.combine(first_day, time.min, tzinfo=zone)
    window_end = window_start + timedelta(days=HORIZON_DAYS)
    busy = await _booked_windows(db, interviewer.id, window_start, window_end)

    duration = timedelta(minutes=duration_minutes)
    slots: list[datetime] = []
    for offset in range(HORIZON_DAYS):
        day = first_day + timedelta(days=offset)
        window = windows.get(WEEKDAY_KEYS[day.weekday()])
        if window is None:
            continue
        cursor = datetime.combine(day, window[0], tzinfo=zone)
        day_end = datetime.combine(day, window[1], tzinfo=zone)
        while cursor + duration <= day_end:
            if cursor < min_start:
                cursor += timedelta(minutes=SLOT_GRID_MINUTES)
                continue
            conflict = any(
                cursor < b_end and cursor + duration > b_start for b_start, b_end in busy
            )
            if not conflict:
                slots.append(cursor)
            cursor += timedelta(minutes=SLOT_GRID_MINUTES)
    return slots


async def live_slots(db: AsyncSession, interview: Interview) -> list[datetime]:
    """Candidate-visible slots, computed fresh. Empty once cancelled or on a bad zone."""
    if interview.status is InterviewStatus.CANCELLED:
        return []
    try:
        return await generate_slots(
            db,
            interview.interviewer,
            duration_minutes=interview.duration_minutes,
            timezone=interview.timezone,
        )
    except ValueError:
        logger.warning("live slot computation failed for interview %s", interview.id, exc_info=True)
        return []


async def get_for_application(
    db: AsyncSession, company: Company, application_id: uuid.UUID
) -> Interview | None:
    """The application's active (non-cancelled) interview, if any."""
    return (
        await db.execute(
            select(Interview).where(
                Interview.company_id == company.id,
                Interview.application_id == application_id,
                Interview.status != InterviewStatus.CANCELLED,
            )
        )
    ).scalar_one_or_none()


async def create_interview(
    db: AsyncSession,
    company: Company,
    application: Application,
    *,
    interviewer: User,
    title: str,
    description: str,
    duration_minutes: int,
    timezone: str,
    location: str = "",
    actor_user_id: uuid.UUID | None = None,
) -> Interview:
    if await get_for_application(db, company, application.id) is not None:
        raise InterviewExistsError
    saved_tz, _ = effective_availability(interviewer)
    interview = Interview(
        company_id=company.id,
        application_id=application.id,
        interviewer_user_id=interviewer.id,
        title=title,
        description=description,
        duration_minutes=duration_minutes,
        timezone=saved_tz or timezone,
        location=location.strip(),
    )
    db.add(interview)
    activity.record(
        db,
        company_id=company.id,
        type=activity.INTERVIEW_REQUESTED,
        actor_user_id=actor_user_id,
        application_id=application.id,
        payload={"interviewer": interviewer.email},
    )
    await db.commit()
    await db.refresh(interview)
    return interview


async def cancel_interview(
    db: AsyncSession,
    interview: Interview,
    *,
    interviewer: User,
    actor_user_id: uuid.UUID | None = None,
) -> None:
    """Cancel the request. The caller mails the cancel notices (with the
    METHOD:CANCEL part when a time existed)."""
    interview.status = InterviewStatus.CANCELLED
    activity.record(
        db,
        company_id=interview.company_id,
        type=activity.INTERVIEW_CANCELLED,
        actor_user_id=actor_user_id,
        application_id=interview.application_id,
    )
    await scorecards_service.dismiss_for_interview(db, interview, actor_user_id=actor_user_id)
    await db.commit()


async def get_by_id_public(db: AsyncSession, interview_id: uuid.UUID) -> Interview | None:
    """Token-authenticated candidate lookup - the signed token IS the scope."""
    return (
        await db.execute(
            select(Interview)
            .where(Interview.id == interview_id)
            .options(
                selectinload(Interview.application).selectinload(Application.candidate),
                selectinload(Interview.application).selectinload(Application.job),
            )
        )
    ).scalar_one_or_none()


async def _lock_interviewer(db: AsyncSession, interviewer_id: uuid.UUID) -> None:
    """Serialize bookings per interviewer for the rest of the transaction.

    Taken after the slot computation, so the hold time is the DB re-check
    and the status write only. lock_timeout turns a hung holder into a
    fast, retryable failure for the waiters.
    """
    key = int.from_bytes(hashlib.sha256(interviewer_id.bytes).digest()[:8], "big", signed=True)
    await db.execute(text(f"SET LOCAL lock_timeout = '{int(LOCK_TIMEOUT_MS)}ms'"))
    try:
        await db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": key})
    except DBAPIError as exc:
        raise LockBusyError from exc


async def _require_unbooked(db: AsyncSession, interview: Interview, start: datetime) -> None:
    """DB-side conflict check for under the lock: no BOOKED Ganek interview
    of this interviewer overlaps the chosen window. The slot set was
    computed before the lock; what can change between that computation and
    the lock being granted is only what other bookers commit here."""
    duration = timedelta(minutes=interview.duration_minutes)
    busy = await _booked_windows(
        db,
        interview.interviewer_user_id,
        start - timedelta(minutes=MAX_INTERVIEW_MINUTES),
        start + duration,
    )
    if any(start < b_end and start + duration > b_start for b_start, b_end in busy):
        raise SlotUnavailableError


async def _require_available(db: AsyncSession, interview: Interview, start: datetime) -> None:
    """The chosen instant must be in the freshly-computed live slot set
    (availability minus Ganek's own bookings). Called BEFORE the lock."""
    slots = await generate_slots(
        db,
        interview.interviewer,
        duration_minutes=interview.duration_minutes,
        timezone=interview.timezone,
    )
    if start not in slots:  # aware datetimes compare by instant
        raise SlotUnavailableError


async def _queue_reminder(interview: Interview, start: datetime) -> str | None:
    """T-24h reminder to both sides; the job re-validates, so stale ones no-op."""
    fire_at = start - timedelta(hours=24)
    if fire_at <= datetime.now(UTC):
        return None  # booked within 24h of the slot - no reminder needed
    job_id = f"iv-{interview.id}-{int(start.timestamp())}"
    queued = await queue.enqueue(
        "send_interview_reminder",
        str(interview.id),
        start.isoformat(),
        defer_until=fire_at,
        job_id=job_id,
    )
    return job_id if queued else None


async def book(db: AsyncSession, interview: Interview, *, start: datetime) -> Interview:
    """Candidate picks a slot: re-check the live slot set, lock, write the
    booking. The route queues the confirmation and the interviewer invite
    (each with the .ics) after this commits.
    """
    if interview.status is InterviewStatus.BOOKED:
        raise AlreadyBookedError  # cheap pre-lock fast path
    start = start.astimezone(UTC)
    # slot computation first, lock second: only the DB-side conflicts get
    # re-checked once the lock is ours.
    await _require_available(db, interview, start)
    await _lock_interviewer(db, interview.interviewer_user_id)
    # authoritative re-check: another request may have booked this same
    # interview between our load and acquiring the lock (double-submit /
    # two tabs) - `interview` is stale in-memory (expire_on_commit=False).
    await db.refresh(interview, attribute_names=["status"])
    status_after_lock: InterviewStatus = interview.status
    if status_after_lock is InterviewStatus.BOOKED:
        raise AlreadyBookedError
    await _require_unbooked(db, interview, start)
    interview.status = InterviewStatus.BOOKED
    interview.scheduled_start = start
    interview.ics_sequence = 0
    activity.record(
        db,
        company_id=interview.company_id,
        type=activity.INTERVIEW_BOOKED,
        application_id=interview.application_id,
        payload={"start": start.isoformat()},
    )
    interview.reminder_job_id = await _queue_reminder(interview, start)
    await _request_scorecard(db, interview, start)
    await db.commit()  # also commits the scorecard row (request runs with notify=False)
    return interview


async def _request_scorecard(db: AsyncSession, interview: Interview, start: datetime) -> None:
    """Ask the interviewer for a scorecard once the slot is booked (spec 4.3).
    Reached from the public route, so nothing here may fail the booking."""
    interviewer = interview.interviewer
    if not interviewer.is_active:
        return
    application = (
        await db.execute(
            select(Application).where(
                Application.id == interview.application_id,
                Application.company_id == interview.company_id,
            )
        )
    ).scalar_one()
    try:
        await scorecards_service.request(
            db,
            application=application,
            reviewer=interviewer,
            requested_by=None,
            interview_id=interview.id,
            due_from=start + timedelta(minutes=interview.duration_minutes),
            notify=False,
        )
    except scorecards_service.AlreadyOpenError:
        pass  # an open or submitted row already exists for this reviewer


async def reschedule(db: AsyncSession, interview: Interview, *, start: datetime) -> Interview:
    """Move a booked interview. Bumps the iTIP sequence so the new invite
    replaces the old event in both calendars; the route mails it."""
    if interview.status is not InterviewStatus.BOOKED:
        raise NotBookedError  # cheap pre-lock fast path
    start = start.astimezone(UTC)
    await _require_available(db, interview, start)  # slot set before the lock, as in book()
    await _lock_interviewer(db, interview.interviewer_user_id)
    # authoritative re-check under lock, same reasoning as book(); also
    # refreshes ics_sequence so a concurrent reschedule is built upon.
    await db.refresh(interview, attribute_names=["status", "ics_sequence"])
    if interview.status is not InterviewStatus.BOOKED:
        raise NotBookedError
    await _require_unbooked(db, interview, start)
    interview.scheduled_start = start
    interview.ics_sequence = interview.ics_sequence + 1
    interview.reminder_job_id = await _queue_reminder(interview, start)
    await scorecards_service.reschedule_for_interview(db, interview, start=start)
    await db.commit()
    return interview


async def candidate_cancel(db: AsyncSession, interview: Interview) -> Interview:
    """Candidate-side cancel; the recruiter can issue a fresh request later.
    The route mails the interviewer's cancel notice."""
    if interview.status is InterviewStatus.CANCELLED:
        return interview
    interview.status = InterviewStatus.CANCELLED
    activity.record(
        db,
        company_id=interview.company_id,
        type=activity.INTERVIEW_CANCELLED,
        application_id=interview.application_id,
    )
    await scorecards_service.dismiss_for_interview(
        db, interview, actor_user_id=None, reason="interview_cancelled"
    )
    await db.commit()
    return interview
