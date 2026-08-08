"""Interview scheduling (single-round v1).

Slot offers are computed once from the interviewer's Google free/busy and
frozen on the interview row; booking (PR ③) re-checks the chosen slot
against live free/busy before creating the calendar event.
"""

import logging
import uuid
from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import Application, Company, Interview, InterviewStatus, User
from app.services import google_calendar

logger = logging.getLogger(__name__)

SLOT_GRID_MINUTES = 30
WORKDAY_START = time(9, 0)
WORKDAY_END = time(18, 0)


class InterviewExistsError(Exception):
    """The application already has a pending or booked interview."""


class AlreadyBookedError(Exception):
    """Booking attempted on an interview that already has a time."""


class NotBookedError(Exception):
    """Reschedule attempted before any slot was booked."""


class SlotUnavailableError(Exception):
    """The chosen slot is not offered, already past, or just got taken."""


async def generate_slots(
    db: AsyncSession,
    interviewer: User,
    *,
    duration_minutes: int,
    timezone: str,
    business_days: int = 10,
    per_day_cap: int = 4,
) -> list[datetime]:
    """Free 30-min-grid starts over the next N business days, interviewer tz.

    Raises ValueError for an unknown IANA zone and lets
    google_calendar.NeedsReconnectError bubble to the caller.
    """
    try:
        zone = ZoneInfo(timezone)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ValueError(f"unknown timezone {timezone!r}") from exc

    now = datetime.now(zone)
    window_start = datetime.combine(now.date() + timedelta(days=1), WORKDAY_START, tzinfo=zone)
    window_end = window_start + timedelta(days=16)  # 10 business days always fit
    busy = await google_calendar.freebusy(db, interviewer, window_start, window_end)

    slots: list[datetime] = []
    day = now.date() + timedelta(days=1)
    counted_days = 0
    duration = timedelta(minutes=duration_minutes)
    while counted_days < business_days:
        if day.weekday() < 5:
            counted_days += 1
            taken_today = 0
            cursor = datetime.combine(day, WORKDAY_START, tzinfo=zone)
            day_end = datetime.combine(day, WORKDAY_END, tzinfo=zone)
            while cursor + duration <= day_end and taken_today < per_day_cap:
                end = cursor + duration
                conflict = any(
                    cursor < busy_end and end > busy_start for busy_start, busy_end in busy
                )
                if not conflict:
                    slots.append(cursor)
                    taken_today += 1
                cursor += timedelta(minutes=SLOT_GRID_MINUTES)
        day += timedelta(days=1)
    return slots


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
    slots: list[datetime],
) -> Interview:
    if await get_for_application(db, company, application.id) is not None:
        raise InterviewExistsError
    interview = Interview(
        company_id=company.id,
        application_id=application.id,
        interviewer_user_id=interviewer.id,
        title=title,
        description=description,
        duration_minutes=duration_minutes,
        timezone=timezone,
        offered_slots=[slot.astimezone(UTC).isoformat() for slot in slots],
    )
    db.add(interview)
    await db.commit()
    await db.refresh(interview)
    return interview


async def cancel_interview(db: AsyncSession, interview: Interview, *, interviewer: User) -> None:
    """Cancel the request; a booked calendar event is removed best-effort."""
    if interview.google_event_id is not None:
        try:
            await google_calendar.delete_event(db, interviewer, interview.google_event_id)
        except google_calendar.GoogleCalendarError:
            logger.warning(
                "calendar event delete failed for interview %s", interview.id, exc_info=True
            )
    interview.status = InterviewStatus.CANCELLED
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


def available_slots(
    interview: Interview, *, lead_time: timedelta = timedelta(hours=1)
) -> list[datetime]:
    """Offered slots that are still in the (near) future, sorted."""
    horizon = datetime.now(UTC) + lead_time
    slots = []
    for raw in interview.offered_slots:
        try:
            slot = datetime.fromisoformat(raw)
        except ValueError:
            continue
        if slot > horizon:
            slots.append(slot)
    return sorted(slots)


def _require_offered(interview: Interview, start: datetime) -> None:
    if start.astimezone(UTC) not in available_slots(interview):
        raise SlotUnavailableError


async def _slot_is_free(db: AsyncSession, interview: Interview, start: datetime) -> bool:
    end = start + timedelta(minutes=interview.duration_minutes)
    busy = await google_calendar.freebusy(db, interview.interviewer, start, end)
    return not any(start < busy_end and end > busy_start for busy_start, busy_end in busy)


async def book(db: AsyncSession, interview: Interview, *, start: datetime) -> Interview:
    """Candidate picks a slot: re-check live free/busy, create the Meet event.

    Google emails the calendar invite (sendUpdates=all) — that is the
    design's "invite lands in your inbox".
    """
    if interview.status is InterviewStatus.BOOKED:
        raise AlreadyBookedError
    start = start.astimezone(UTC)
    _require_offered(interview, start)
    if not await _slot_is_free(db, interview, start):
        raise SlotUnavailableError
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
    await db.commit()
    return interview


async def reschedule(db: AsyncSession, interview: Interview, *, start: datetime) -> Interview:
    if interview.status is not InterviewStatus.BOOKED or interview.google_event_id is None:
        raise NotBookedError
    start = start.astimezone(UTC)
    _require_offered(interview, start)
    if not await _slot_is_free(db, interview, start):
        raise SlotUnavailableError
    await google_calendar.patch_event_time(
        db,
        interview.interviewer,
        interview.google_event_id,
        start=start,
        end=start + timedelta(minutes=interview.duration_minutes),
        timezone=interview.timezone,
    )
    interview.scheduled_start = start
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
    await db.commit()
    return interview
