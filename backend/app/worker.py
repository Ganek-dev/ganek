"""arq worker: scheduled emails (interview reminders, quiz auto-nudges).

Run with: arq app.worker.WorkerSettings

Every job is self-validating — it was scheduled against a snapshot of
state (the booked start, a pending attempt) and quietly no-ops when the
world moved on (reschedule, cancel, completion). That is what lets the
web side enqueue-and-forget without abort machinery.
"""

import logging
import math
from datetime import UTC, datetime
from typing import Any

from arq.connections import RedisSettings
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import selectinload
from sqlalchemy.pool import NullPool

from app.core.config import settings
from app.core.security import create_quiz_token
from app.models import Application, Company, Interview, InterviewStatus, QuizAttempt
from app.models.quiz import AttemptStatus
from app.services import company as company_service
from app.services import email as email_service

logger = logging.getLogger(__name__)


async def startup(ctx: dict[str, Any]) -> None:
    engine = create_async_engine(settings.database_url, poolclass=NullPool)
    ctx["engine"] = engine
    ctx["session_factory"] = async_sessionmaker(engine, expire_on_commit=False)


async def shutdown(ctx: dict[str, Any]) -> None:
    await ctx["engine"].dispose()


async def send_interview_reminder(
    ctx: dict[str, Any], interview_id: str, expected_start_iso: str
) -> None:
    """T-24h candidate reminder. The interviewer is deliberately not emailed —
    their own Google Calendar event already carries native reminders."""
    async with ctx["session_factory"]() as db:
        interview = (
            await db.execute(
                select(Interview)
                .where(Interview.id == interview_id)
                .options(
                    selectinload(Interview.application).selectinload(Application.candidate),
                    selectinload(Interview.application).selectinload(Application.job),
                )
            )
        ).scalar_one_or_none()
        if interview is None or interview.status is not InterviewStatus.BOOKED:
            return
        start = interview.scheduled_start
        if start is None or start.isoformat() != expected_start_iso:
            return  # rescheduled — the new booking queued its own reminder
        if start <= datetime.now(UTC):
            return
        company = (
            await db.execute(select(Company).where(Company.id == interview.company_id))
        ).scalar_one()
        candidate = interview.application.candidate
        email_service.send_interview_reminder(
            to=candidate.email,
            candidate_name=candidate.name,
            job_title=interview.application.job.title,
            company_name=company.name,
            start=start,
            timezone=interview.timezone,
            meet_url=interview.meet_url,
            brand_primary=(company.theme or {}).get("primary_color"),
            controller_name=company_service.controller_name(company),
            privacy_url=company_service.privacy_notice_url(company),
        )


async def send_quiz_nudge(ctx: dict[str, Any], attempt_id: str) -> None:
    """Auto-nudge (17b) shortly before a pending quiz link expires."""
    async with ctx["session_factory"]() as db:
        attempt = (
            await db.execute(
                select(QuizAttempt)
                .where(QuizAttempt.id == attempt_id)
                .options(
                    selectinload(QuizAttempt.application).selectinload(Application.candidate),
                    selectinload(QuizAttempt.application).selectinload(Application.job),
                )
            )
        ).scalar_one_or_none()
        now = datetime.now(UTC)
        if attempt is None or attempt.status is not AttemptStatus.PENDING:
            return
        if attempt.expires_at <= now:
            return
        company = (
            await db.execute(select(Company).where(Company.id == attempt.company_id))
        ).scalar_one()
        candidate = attempt.application.candidate
        days_left = max(0, math.ceil((attempt.expires_at - now).total_seconds() / 86400))
        email_service.send_quiz_reminder(
            to=candidate.email,
            candidate_name=candidate.name,
            job_title=attempt.application.job.title,
            company_name=company.name,
            brand_primary=(company.theme or {}).get("primary_color"),
            quiz_url=f"{settings.public_base_url.rstrip('/')}/quiz/{create_quiz_token(attempt.id)}",
            expires_at=attempt.expires_at,
            days_left=days_left,
            controller_name=company_service.controller_name(company),
            privacy_url=company_service.privacy_notice_url(company),
        )


class WorkerSettings:
    functions = [send_interview_reminder, send_quiz_nudge]
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = RedisSettings.from_dsn(settings.redis_url)
    max_tries = 3
