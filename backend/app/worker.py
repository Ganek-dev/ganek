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

from app.core import urls
from app.core.config import settings
from app.core.logcfg import configure_logging
from app.core.observability import init_sentry
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
from app.services import health as health_service
from app.services import outbox as outbox_service
from app.services import retention as retention_service

logger = logging.getLogger(__name__)

# a purge claim outlives the longest plausible run but not the next night's tick
PURGE_CLAIM_TTL_SECONDS = 20 * 3600


async def startup(ctx: dict[str, Any]) -> None:
    # after arq applied its own logging config: same format and handler as the API
    configure_logging(json_logs=settings.log_format == "json", level=settings.log_level)
    init_sentry(dsn=settings.sentry_dsn, component="worker")
    engine = create_async_engine(settings.database_url, poolclass=NullPool)
    ctx["engine"] = engine
    ctx["session_factory"] = async_sessionmaker(engine, expire_on_commit=False)
    await heartbeat(ctx)  # visible to /api/health/deep before the first cron tick


async def _mark(ctx: dict[str, Any], key: str, *, ttl_seconds: int | None = None) -> None:
    """Best-effort liveness bookkeeping for /api/health/deep. Never lets a
    Redis hiccup fail the job that called it."""
    redis = ctx.get("redis")
    if redis is None:
        return
    try:
        await redis.set(key, datetime.now(UTC).isoformat(), ex=ttl_seconds)
    except Exception:  # noqa: BLE001 - bookkeeping only
        logger.warning("could not write %s", key, exc_info=True)


async def _claim_run(ctx: dict[str, Any], name: str, *, now: datetime, ttl_seconds: int) -> bool:
    """Cross-worker cron dedupe (card A8): the first worker to claim ``name``
    for today's run wins, the others skip.

    arq already dedupes a cron tick through its unique job id when every
    worker agrees on the minute; this covers skewed clocks, restarts that
    replay a missed tick, and operators who scale ``worker`` freely. No
    Redis in ctx (direct job calls in tests) or a Redis error means run
    anyway: a double purge is idempotent and merely wasteful, a skipped
    purge breaks the notice's retention promise.
    """
    redis = ctx.get("redis")
    if redis is None:
        return True
    key = f"ganek:cron:{name}:{now.date().isoformat()}"
    try:
        claimed = await redis.set(key, now.isoformat(), nx=True, ex=ttl_seconds)
    except Exception:  # noqa: BLE001 - bookkeeping only
        logger.warning("could not claim %s; running anyway", key, exc_info=True)
        return True
    if not claimed:
        logger.info("%s already ran today on another worker; skipping", name)
    return bool(claimed)


async def heartbeat(ctx: dict[str, Any]) -> None:
    """Minute cron: proves the worker process is alive and can reach Redis."""
    await _mark(
        ctx, health_service.WORKER_SEEN_KEY, ttl_seconds=health_service.WORKER_SEEN_TTL_SECONDS
    )


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
            privacy_url=urls.privacy_notice_url(company),
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
            quiz_url=urls.quiz_url(company, create_quiz_token(attempt.id)),
            expires_at=attempt.expires_at,
            days_left=days_left,
            controller_name=company_service.controller_name(company),
            privacy_url=urls.privacy_notice_url(company),
        )


async def purge_retention(ctx: dict[str, Any]) -> None:
    """Nightly Art. 5(1)(e) enforcement — the notice's retention promise,
    kept. Per-company windows, hired excluded, failures retried next night.
    Runs once per day across however many workers are up."""
    now = datetime.now(UTC)
    if not await _claim_run(ctx, "purge_retention", now=now, ttl_seconds=PURGE_CLAIM_TTL_SECONDS):
        return
    async with ctx["session_factory"]() as db:
        summary = await retention_service.run_purge(db, now=now)
    logger.info("retention purge: %s", summary)
    await _mark(ctx, health_service.LAST_PURGE_KEY)


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
        if not email_service.configured():
            # not retryable by waiting: an operator has to configure a provider
            row.status = EmailStatus.FAILED
            row.last_error = "Email not configured"
            await db.commit()
            return
        skip = await outbox_service.suppressed_for(db, row)
        if skip is not None:
            # card A7: the address bounced or complained; no provider call
            row.status = EmailStatus.SUPPRESSED
            row.last_error = skip
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
        heartbeat,
    ]
    cron_jobs = [
        cron(purge_retention, hour=3, minute=17),
        cron(sweep_outbox, minute={7, 17, 27, 37, 47, 57}),
        cron(heartbeat),  # every minute
    ]
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = RedisSettings.from_dsn(settings.redis_url)
    max_tries = 3
    # arq refreshes its own health key at this interval; the compose
    # healthcheck runs `arq --check` against it
    health_check_interval = 60
