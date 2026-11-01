"""arq worker: scheduled emails (interview reminders, quiz auto-nudges).

Run with: arq app.worker.WorkerSettings

Every job is self-validating - it was scheduled against a snapshot of
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
    Candidate,
    Company,
    EmailOutbox,
    EmailStatus,
    Interview,
    InterviewStatus,
    Job,
    QuizAttempt,
    User,
)
from app.models.quiz import AttemptStatus
from app.models.scorecard import Scorecard
from app.models.webhook import DeliveryStatus, WebhookDelivery
from app.services import company as company_service
from app.services import demo_seed, email_templates
from app.services import email as email_service
from app.services import health as health_service
from app.services import outbox as outbox_service
from app.services import retention as retention_service
from app.services import scorecards as scorecards_service
from app.services import webhooks as webhooks_service

logger = logging.getLogger(__name__)

# a purge claim outlives the longest plausible run but not the next night's tick
PURGE_CLAIM_TTL_SECONDS = 20 * 3600
REMIND_CLAIM_TTL_SECONDS = 20 * 3600


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
    """T-24h reminder to the candidate and the interviewer. Re-validates the
    booking, so a stale job (rescheduled, cancelled, past) no-ops."""
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
            return  # rescheduled - the new booking queued its own reminder
        if start <= datetime.now(UTC):
            return
        company = (
            await db.execute(select(Company).where(Company.id == interview.company_id))
        ).scalar_one()
        candidate = interview.application.candidate
        interviewer = interview.interviewer
        email_service.send_interview_reminder(
            to=candidate.email,
            ref=str(interview.application_id),
            candidate_name=candidate.name,
            job_title=interview.application.job.title,
            company_name=company.name,
            start=start,
            timezone=interview.timezone,
            location=interview.location,
            brand_primary=(company.theme or {}).get("primary_color"),
            controller_name=company_service.controller_name(company),
            privacy_url=urls.privacy_notice_url(company),
        )
        email_service.send_interview_reminder_interviewer(
            to=interviewer.email,
            ref=str(interview.application_id),
            interviewer_name=interviewer.display_label,
            candidate_name=candidate.name,
            job_title=interview.application.job.title,
            company_name=company.name,
            start=start,
            timezone=interview.timezone,
            location=interview.location,
            applicant_url=urls.admin_applicant_url(company, interview.application_id),
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
        template_id, template = await email_templates.resolve(db, company.id, "quiz_reminder")
        email_service.send_quiz_reminder(
            to=candidate.email,
            template_id=str(template_id) if template_id is not None else None,
            template_subject=template.subject,
            template_body=template.body,
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
    """Nightly Art. 5(1)(e) enforcement - the notice's retention promise,
    kept. Per-company windows, hired excluded, failures retried next night.
    Runs once per day across however many workers are up."""
    now = datetime.now(UTC)
    if not await _claim_run(ctx, "purge_retention", now=now, ttl_seconds=PURGE_CLAIM_TTL_SECONDS):
        return
    async with ctx["session_factory"]() as db:
        summary = await retention_service.run_purge(db, now=now)
    logger.info("retention purge: %s", summary)
    await _mark(ctx, health_service.LAST_PURGE_KEY)


async def remind_scorecards(ctx: dict[str, Any]) -> None:
    """Daily scorecard nudge: one mail per request lifetime to reviewers whose
    request has waited 3+ days. Once per day across workers.

    Per row, `reminded_at` and the outbox row go in ONE commit (queue_email
    commits the session; in demo mode it does not, so we commit ourselves and
    mark without mailing). A crash before the commit repeats nothing and loses
    nothing; after it both are durable. A failing row is rolled back and
    retried tomorrow without stopping the others."""
    now = datetime.now(UTC)
    if not await _claim_run(
        ctx, "remind_scorecards", now=now, ttl_seconds=REMIND_CLAIM_TTL_SECONDS
    ):
        return
    sent = failed = 0
    async with ctx["session_factory"]() as db:
        # ids only: a rollback expires loaded rows and async sessions cannot lazy-load
        row_ids = [r.id for r in await scorecards_service.due_for_reminder(db, now=now)]
        for row_id in row_ids:
            try:
                row = await db.get(Scorecard, row_id)
                if row is None or row.reminded_at is not None:
                    continue
                application = await db.get(Application, row.application_id)
                company = await db.get(Company, row.company_id)
                reviewer = await db.get(User, row.reviewer_user_id)
                assert application is not None and company is not None and reviewer is not None
                candidate = await db.get(Candidate, application.candidate_id)
                job = await db.get(Job, application.job_id)
                assert candidate is not None and job is not None
                days = scorecards_service.waiting_days(row, now=now)
                await scorecards_service.mark_reminded(db, [row], now=now)
                await outbox_service.queue_email(
                    db,
                    kind="scorecard_reminder",
                    company_id=company.id,
                    application_id=application.id,
                    to=reviewer.email,
                    ref=str(application.id),
                    company_name=company.name,
                    candidate_name=candidate.name,
                    job_title=job.title,
                    url=urls.scorecard_url(
                        company,
                        application.id,
                        reviewer=scorecards_service._is_reviewer_role(reviewer),
                    ),
                    waiting_days=days,
                    brand_primary=(company.theme or {}).get("primary_color"),
                )
                await db.commit()  # queue_email skips its own commit in demo mode
                sent += 1
            except Exception:  # noqa: BLE001 - one row must never block the rest
                logger.exception("scorecard reminder failed for %s", row_id)
                await db.rollback()
                failed += 1
    logger.info("scorecard reminders: %d queued, %d failed", sent, failed)


async def reset_demo(ctx: dict[str, Any]) -> None:
    """Nightly rebuild of the public demo workspace. Off while
    GANEK_DEMO_RESET_SLUG is unset. The seed deletes the company (and its CV
    objects) and recreates it, so visitors always find the same lived-in
    workspace whatever yesterday's visitors did to it. Once per day across
    workers, like the purge."""
    slug = settings.demo_reset_slug
    if not slug:
        return
    now = datetime.now(UTC)
    if not await _claim_run(ctx, "reset_demo", now=now, ttl_seconds=PURGE_CLAIM_TTL_SECONDS):
        return
    async with ctx["session_factory"]() as db:
        result = await demo_seed.seed(
            db,
            slug=slug,
            password=settings.demo_password or demo_seed.DEFAULT_PASSWORD,
            reset=True,
        )
    logger.info(
        "demo reset: company '%s' rebuilt with %d applications and %d completed quizzes",
        slug,
        result.applications,
        result.attempts,
    )


async def deliver_email(ctx: dict[str, Any], outbox_id: str) -> None:
    """Send one outbox row. Self-validating: only rows still `queued` are
    touched, so duplicate enqueues (sweeper races) are harmless.

    Retry policy lives HERE, not in arq's max_tries: each transport failure
    is recorded on the row, retried with backoff via Retry, and parked as
    `failed` after outbox.MAX_ATTEMPTS - visible on the applicant panel
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


async def deliver_webhook(ctx: dict[str, Any], delivery_id: str) -> None:
    """POST one webhook delivery (card D4 part B). Mirrors deliver_email:
    only `queued` rows are touched, the attempt counter and the parked
    `failed` state live on the row, retries go through arq's Retry."""
    async with ctx["session_factory"]() as db:
        row = (
            await db.execute(select(WebhookDelivery).where(WebhookDelivery.id == delivery_id))
        ).scalar_one_or_none()
        if row is None or row.status is not DeliveryStatus.QUEUED:
            return
        row.attempts += 1
        try:
            await webhooks_service.deliver(db, row)
        except Exception as exc:  # noqa: BLE001 - every failure drives the retry loop
            row.last_error = str(exc)[: webhooks_service.MAX_ERROR_LENGTH] or exc.__class__.__name__
            if row.attempts >= webhooks_service.MAX_ATTEMPTS:
                row.status = DeliveryStatus.FAILED
                await db.commit()
                logger.warning("webhook %s failed after %d attempts", delivery_id, row.attempts)
                return
            delay = webhooks_service.RETRY_DELAYS_SECONDS[
                min(row.attempts - 1, len(webhooks_service.RETRY_DELAYS_SECONDS) - 1)
            ]
            await db.commit()
            raise Retry(defer=delay) from exc
        await db.commit()


async def sweep_webhooks(ctx: dict[str, Any]) -> None:
    """Re-enqueue queued deliveries whose enqueue was lost (redis down)."""
    async with ctx["session_factory"]() as db:
        stuck = await webhooks_service.stuck_deliveries(
            db, older_than=datetime.now(UTC) - timedelta(minutes=5)
        )
    for row_id in stuck:
        await ctx["redis"].enqueue_job("deliver_webhook", str(row_id))
    if stuck:
        logger.info("webhook sweep: re-enqueued %d deliveries", len(stuck))


class WorkerSettings:
    functions = [
        send_interview_reminder,
        send_quiz_nudge,
        purge_retention,
        remind_scorecards,
        reset_demo,
        deliver_email,
        sweep_outbox,
        deliver_webhook,
        sweep_webhooks,
        heartbeat,
    ]
    cron_jobs = [
        cron(purge_retention, hour=3, minute=17),
        cron(remind_scorecards, hour=9, minute=5),
        cron(reset_demo, hour=4, minute=7),  # no-op unless GANEK_DEMO_RESET_SLUG is set
        cron(sweep_outbox, minute={7, 17, 27, 37, 47, 57}),
        cron(sweep_webhooks, minute={3, 13, 23, 33, 43, 53}),
        cron(heartbeat),  # every minute
    ]
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = RedisSettings.from_dsn(settings.redis_url)
    max_tries = 3
    # arq refreshes its own health key at this interval; the compose
    # healthcheck runs `arq --check` against it
    health_check_interval = 60
