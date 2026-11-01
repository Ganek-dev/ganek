import uuid
from datetime import datetime, time
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.api.deps import CurrentCompany, CurrentUser, DbSession, StaffCompany, StaffUser
from app.models import Application, Interview, InterviewStatus
from app.schemas.dashboard import QueueDismiss, QueueOut, TodayEvent, TodayOut
from app.schemas.stats import BoardOut, Period, ReportsOut, StatsOverview
from app.services import pipeline_signals, reports
from app.services import queue as queue_service
from app.services import stats as stats_service

router = APIRouter(prefix="/stats", tags=["stats"])


@router.get("/overview", response_model=StatsOverview)
async def stats_overview(db: DbSession, company: StaffCompany) -> StatsOverview:
    return await stats_service.overview(db, company)


@router.get("/board", response_model=BoardOut)
async def stats_board(db: DbSession, company: StaffCompany) -> BoardOut:
    """Dashboard open roles board: one row per published job (and closed jobs
    that still hold live candidates), with the stalled/attention chip."""
    return await pipeline_signals.board(db, company)


@router.get("/reports", response_model=ReportsOut)
async def stats_reports(
    db: DbSession,
    company: StaffCompany,
    period: Period = "90d",
    job_id: uuid.UUID | None = None,
) -> ReportsOut:
    """Reports page: the cohort of applications created in the period, its
    funnel, time in stage, time to hire and sources, against the previous period."""
    return await reports.reports(db, company, period=period, job_id=job_id)


@router.get("/today", response_model=TodayOut)
async def today(db: DbSession, company: StaffCompany, user: StaffUser, tz: str = "UTC") -> TodayOut:
    """Dashboard Today panel: the signed-in user's booked interviews for the
    day. Never 500s on a weird browser timezone - falls back to UTC."""
    try:
        ZoneInfo(tz)
    except (ZoneInfoNotFoundError, ValueError):
        tz = "UTC"
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
        events=[
            TodayEvent(
                start=iv.scheduled_start.isoformat() if iv.scheduled_start else None,
                summary=f"{iv.title} - {iv.application.candidate.name}",
                location=iv.location,
            )
            for iv in interviews
        ],
    )


@router.get("/queue", response_model=QueueOut)
async def queue(db: DbSession, company: CurrentCompany, user: CurrentUser) -> QueueOut:
    """Dashboard "Your queue" derived items (card D13): published jobs
    without a quiz, completed quizzes with unreviewed integrity flags,
    interview invites the candidate has not booked, scorecards left waiting
    3+ days and stalled roles (staff) and the user's own open scorecards. Minus what this user
    dismissed."""
    return QueueOut(items=await queue_service.visible_items(db, company, user))


@router.post("/queue/dismiss", status_code=status.HTTP_204_NO_CONTENT)
async def dismiss_queue_item(
    payload: QueueDismiss, db: DbSession, company: CurrentCompany, user: CurrentUser
) -> None:
    if not await queue_service.dismiss(db, company, user, payload.key):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Queue item not found")
