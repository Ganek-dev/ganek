"""arq worker: scheduled emails (interview reminders, quiz auto-nudges).

Run with: arq app.worker.WorkerSettings

Every job is self-validating — it was scheduled against a snapshot of
state (the booked start, a pending attempt) and quietly no-ops when the
world moved on (reschedule, cancel, completion). That is what lets the
web side enqueue-and-forget without abort machinery.
"""

import logging
import math
from datetime import UTC, datetime, timedelta
from typing import Any

from arq import Retry, cron
from arq.connections import RedisSettings
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import selectinload
from sqlalchemy.pool import NullPool

from app.core.config import settings
from app.core.security import create_quiz_token
from app.models import (
    Application,
    Company,
    EmailOutbox,
    EmailStatus,
    Interview,
    InterviewStatus,
    QuizAttempt,
)
from app.models.quiz import AttemptStatus
from app.services import company as company_service
from app.services import email as email_service
from app.services import outbox as outbox_service
from app.services import retention as retention_service

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
            ref=str(interview.application_id),
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
            ref=str(attempt.application_id),
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


async def purge_retention(ctx: dict[str, Any]) -> None:
    """Nightly Art. 5(1)(e) enforcement — the notice's retention promise,
    kept. Per-company windows, hired excluded, failures retried next night."""
    async with ctx["session_factory"]() as db:
        summary = await retention_service.run_purge(db, now=datetime.now(UTC))
    logger.info("retention purge: %s", summary)


async def deliver_email(ctx: dict[str, Any], outbox_id: str) -> None:
    """Send one outbox row. Self-validating: only rows still `queued` are
    touched, so duplicate enqueues (sweeper races) are harmless.

    Retry policy lives HERE, not in arq's max_tries: each transport failure
    is recorded on the row, retried with backoff via Retry, and parked as
    `failed` after outbox.MAX_ATTEMPTS — visible on the applicant panel
    instead of vanishing into a log.
    """
    async with ctx["session_factory"]() as db:
        row = (
            await db.execute(select(EmailOutbox).where(EmailOutbox.id == outbox_id))
        ).scalar_one_or_none()
        if row is None or row.status is not EmailStatus.QUEUED:
            return
        if not email_service.smtp_configured():
            # not retryable by waiting — an operator has to set GANEK_SMTP_*
            row.status = EmailStatus.FAILED
            row.last_error = "SMTP not configured"
            await db.commit()
            return
        row.attempts += 1
        try:
            outbox_service.dispatch(row)
        except Exception as exc:  # noqa: BLE001 - transport errors drive the retry loop
            row.last_error = str(exc)[:500] or exc.__class__.__name__
            if row.attempts >= outbox_service.MAX_ATTEMPTS:
                row.status = EmailStatus.FAILED
                await db.commit()
                logger.warning("email %s failed after %d attempts", outbox_id, row.attempts)
                return
            delay = outbox_service.RETRY_DELAYS_SECONDS[
                min(row.attempts - 1, len(outbox_service.RETRY_DELAYS_SECONDS) - 1)
            ]
            await db.commit()
            raise Retry(defer=delay) from exc
        row.status = EmailStatus.SENT
        row.sent_at = datetime.now(UTC)
        row.last_error = None
        await db.commit()


async def sweep_outbox(ctx: dict[str, Any]) -> None:
    """Re-enqueue queued rows whose original enqueue was lost (redis was
    down when the request committed them). Late beats lost."""
    async with ctx["session_factory"]() as db:
        stuck = await outbox_service.stuck_rows(
            db, older_than=datetime.now(UTC) - timedelta(minutes=5)
        )
    for row_id in stuck:
        # no job_id: the original `email-{id}` job may still hold the key;
        # deliver_email's status check makes duplicates no-ops anyway
        await ctx["redis"].enqueue_job("deliver_email", str(row_id))
    if stuck:
        logger.info("outbox sweep: re-enqueued %d emails", len(stuck))


class WorkerSettings:
    functions = [
        send_interview_reminder,
        send_quiz_nudge,
        purge_retention,
        deliver_email,
        sweep_outbox,
    ]
    cron_jobs = [
        cron(purge_retention, hour=3, minute=17),
        cron(sweep_outbox, minute={7, 17, 27, 37, 47, 57}),
    ]
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = RedisSettings.from_dsn(settings.redis_url)
    max_tries = 3
