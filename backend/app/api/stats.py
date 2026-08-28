from datetime import datetime, time
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.api.deps import CurrentCompany, CurrentUser, DbSession
from app.models import Application, Interview, InterviewStatus
from app.schemas.dashboard import TodayEvent, TodayOut
from app.schemas.stats import StatsOverview
from app.services import google_calendar
from app.services import stats as stats_service

router = APIRouter(prefix="/stats", tags=["stats"])


@router.get("/overview", response_model=StatsOverview)
async def stats_overview(db: DbSession, company: CurrentCompany) -> StatsOverview:
    return await stats_service.overview(db, company)


@router.get("/today", response_model=TodayOut)
async def today(
    db: DbSession, company: CurrentCompany, user: CurrentUser, tz: str = "UTC"
) -> TodayOut:
    """Dashboard Today panel: the signed-in user's Google Calendar when
    connected; their booked ganek interviews otherwise. Never 500s on a
    weird browser timezone — falls back to UTC."""
    try:
        ZoneInfo(tz)
    except (ZoneInfoNotFoundError, ValueError):
        tz = "UTC"
    if await google_calendar.get_credential(db, user) is not None:
        try:
            events = await google_calendar.list_today_events(db, user, tz=tz)
            return TodayOut(
                source="google",
                events=[
                    TodayEvent(
                        start=str(e["start"]) if e.get("start") else None,
                        summary=str(e.get("summary") or "(no title)"),
                        hangout_link=(str(e["hangout_link"]) if e.get("hangout_link") else None),
                    )
                    for e in events
                ],
            )
        except google_calendar.GoogleCalendarError:
            pass  # broken consent → ganek fallback below; Account card flags it
    zone = ZoneInfo(tz)
    day = datetime.now(zone).date()
    start = datetime.combine(day, time.min, tzinfo=zone)
    end = datetime.combine(day, time.max, tzinfo=zone)
    interviews = (
        (
            await db.execute(
                select(Interview)
                .where(
                    Interview.company_id == company.id,
                    Interview.interviewer_user_id == user.id,
                    Interview.status == InterviewStatus.BOOKED,
                    Interview.scheduled_start >= start,
                    Interview.scheduled_start <= end,
                )
                .options(selectinload(Interview.application).selectinload(Application.candidate))
                .order_by(Interview.scheduled_start)
            )
        )
        .scalars()
        .all()
    )
    return TodayOut(
        source="vetd",
        events=[
            TodayEvent(
                start=iv.scheduled_start.isoformat() if iv.scheduled_start else None,
                summary=f"{iv.title} — {iv.application.candidate.name}",
                hangout_link=iv.meet_url,
            )
            for iv in interviews
        ],
    )
