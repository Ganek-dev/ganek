"""Interview scheduling (single-round v1).

Slots are always computed live from the interviewer's saved availability
(``effective_availability``) plus Google free/busy plus vetd's own booked
interviews — never frozen on the interview row. Booking re-checks the
chosen slot against live free/busy before creating the calendar event.
"""

import hashlib
import logging
import uuid
from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core import queue
from app.models import Application, Company, Interview, InterviewStatus, User
from app.services import activity, google_calendar

logger = logging.getLogger(__name__)

SLOT_GRID_MINUTES = 30
HORIZON_DAYS = 14  # slots offered over the next two weeks, starting tomorrow
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
    """Compact human summary, compressing runs of identical windows: "Mon–Fri 09:00–17:00"."""
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
        label = DAY_LABELS[first] if first == last else f"{DAY_LABELS[first]}–{DAY_LABELS[last]}"
        parts.append(f"{label} {start:%H:%M}–{end:%H:%M}")
    return " · ".join(parts)


class InterviewExistsError(Exception):
    """The application already has a pending or booked interview."""


class AlreadyBookedError(Exception):
    """Booking attempted on an interview that already has a time."""


class NotBookedError(Exception):
    """Reschedule attempted before any slot was booked."""


class SlotUnavailableError(Exception):
    """The chosen slot is not offered, already past, or just got taken."""


async def _booked_windows(
    db: AsyncSession, interviewer_id: uuid.UUID, window_start: datetime, window_end: datetime
) -> list[tuple[datetime, datetime]]:
    """Busy windows from vetd's own BOOKED interviews — freebusy-lag insurance."""
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

    Raises ValueError for an unknown IANA zone; NeedsReconnectError bubbles.
    """
    saved_tz, windows = effective_availability(interviewer)
    try:
        zone = ZoneInfo(saved_tz or timezone)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ValueError(f"unknown timezone {saved_tz or timezone!r}") from exc

    first_day = datetime.now(zone).date() + timedelta(days=1)
    window_start = datetime.combine(first_day, time.min, tzinfo=zone)
    window_end = window_start + timedelta(days=HORIZON_DAYS)
    busy = await google_calendar.freebusy(db, interviewer, window_start, window_end)
    busy = busy + await _booked_windows(db, interviewer.id, window_start, window_end)

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
            conflict = any(
                cursor < b_end and cursor + duration > b_start for b_start, b_end in busy
            )
            if not conflict:
                slots.append(cursor)
            cursor += timedelta(minutes=SLOT_GRID_MINUTES)
    return slots


async def live_slots(db: AsyncSession, interview: Interview) -> list[datetime]:
    """Candidate-visible slots, computed fresh. Empty on cancelled or calendar trouble."""
    if interview.status is InterviewStatus.CANCELLED:
        return []
    try:
        return await generate_slots(
            db,
            interview.interviewer,
            duration_minutes=interview.duration_minutes,
            timezone=interview.timezone,
        )
    except (ValueError, google_calendar.GoogleCalendarError):
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
    """Cancel the request; a booked calendar event is removed best-effort."""
    if interview.google_event_id is not None:
        try:
            await google_calendar.delete_event(db, interviewer, interview.google_event_id)
        except google_calendar.GoogleCalendarError:
            logger.warning(
                "calendar event delete failed for interview %s", interview.id, exc_info=True
            )
    interview.status = InterviewStatus.CANCELLED
    activity.record(
        db,
        company_id=interview.company_id,
        type=activity.INTERVIEW_CANCELLED,
        actor_user_id=actor_user_id,
        application_id=interview.application_id,
    )
    await db.commit()


async def get_by_id_public(db: AsyncSession, interview_id: uuid.UUID) -> Interview | None:
    """Token-authenticated candidate lookup — the signed token IS the scope."""
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
    """Serialize bookings per interviewer for the rest of the transaction."""
    key = int.from_bytes(hashlib.sha256(interviewer_id.bytes).digest()[:8], "big", signed=True)
    await db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": key})


async def _require_available(db: AsyncSession, interview: Interview, start: datetime) -> None:
    """The chosen instant must be in the freshly-computed live slot set."""
    slots = await generate_slots(
        db,
        interview.interviewer,
        duration_minutes=interview.duration_minutes,
        timezone=interview.timezone,
    )
    if start not in slots:  # aware datetimes compare by instant
        raise SlotUnavailableError


async def _queue_reminder(interview: Interview, start: datetime) -> str | None:
    """T-24h candidate reminder; the job re-validates, so stale ones no-op."""
    fire_at = start - timedelta(hours=24)
    if fire_at <= datetime.now(UTC):
        return None  # booked within 24h of the slot — no reminder needed
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
    """Candidate picks a slot: re-check live free/busy, create the Meet event.

    Google emails the calendar invite (sendUpdates=all) — that is the
    design's "invite lands in your inbox".
    """
    if interview.status is InterviewStatus.BOOKED:
        raise AlreadyBookedError  # cheap pre-lock fast path
    start = start.astimezone(UTC)
    await _lock_interviewer(db, interview.interviewer_user_id)
    # authoritative re-check: another request may have booked this same
    # interview between our load and acquiring the lock (double-submit /
    # two tabs) — `interview` is stale in-memory (expire_on_commit=False).
    await db.refresh(interview, attribute_names=["status"])
    status_after_lock: InterviewStatus = interview.status
    if status_after_lock is InterviewStatus.BOOKED:
        raise AlreadyBookedError
    await _require_available(db, interview, start)
    candidate = interview.application.candidate
    event_id, meet_url = await google_calendar.create_meet_event(
        db,
        interview.interviewer,
        summary=f"{interview.title} — {candidate.name}",
        description=interview.description,
        start=start,
        end=start + timedelta(minutes=interview.duration_minutes),
        attendee_email=candidate.email,
        timezone=interview.timezone,
    )
    interview.status = InterviewStatus.BOOKED
    interview.scheduled_start = start
    interview.google_event_id = event_id
    interview.meet_url = meet_url
    activity.record(
        db,
        company_id=interview.company_id,
        type=activity.INTERVIEW_BOOKED,
        application_id=interview.application_id,
        payload={"start": start.isoformat()},
    )
    interview.reminder_job_id = await _queue_reminder(interview, start)
    await db.commit()
    return interview


async def reschedule(db: AsyncSession, interview: Interview, *, start: datetime) -> Interview:
    if interview.status is not InterviewStatus.BOOKED or interview.google_event_id is None:
        raise NotBookedError  # cheap pre-lock fast path
    start = start.astimezone(UTC)
    await _lock_interviewer(db, interview.interviewer_user_id)
    # authoritative re-check under lock, same reasoning as book(); also
    # refreshes google_event_id so a concurrently-changed event id (e.g.
    # this interview got rescheduled again) is what we actually patch.
    await db.refresh(interview, attribute_names=["status", "google_event_id"])
    if interview.status is not InterviewStatus.BOOKED or interview.google_event_id is None:
        raise NotBookedError
    await _require_available(db, interview, start)
    await google_calendar.patch_event_time(
        db,
        interview.interviewer,
        interview.google_event_id,
        start=start,
        end=start + timedelta(minutes=interview.duration_minutes),
        timezone=interview.timezone,
    )
    interview.scheduled_start = start
    interview.reminder_job_id = await _queue_reminder(interview, start)
    await db.commit()
    return interview


async def candidate_cancel(db: AsyncSession, interview: Interview) -> Interview:
    """Candidate-side cancel; the recruiter can issue a fresh request later."""
    if interview.status is InterviewStatus.CANCELLED:
        return interview
    if interview.google_event_id is not None:
        try:
            await google_calendar.delete_event(db, interview.interviewer, interview.google_event_id)
        except google_calendar.GoogleCalendarError:
            logger.warning(
                "calendar event delete failed for interview %s", interview.id, exc_info=True
            )
    interview.status = InterviewStatus.CANCELLED
    activity.record(
        db,
        company_id=interview.company_id,
        type=activity.INTERVIEW_CANCELLED,
        application_id=interview.application_id,
    )
    await db.commit()
    return interview
