"""Email outbox (M5.7 H4): queue-then-deliver replaces fire-and-forget.

The request that decides to email someone writes an ``email_outbox`` row
and enqueues an arq delivery job. Redis being down only delays delivery -
the sweeper re-enqueues stuck rows. The worker retries transport failures
with backoff and parks the row as ``failed`` after MAX_ATTEMPTS, which the
applicant panel surfaces instead of silence.

``payload`` stores the sender's kwargs verbatim; datetimes ride as
``{"$dt": iso}`` so the round-trip is lossless without per-kind schemas.
"""

import logging
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import queue
from app.core.config import settings
from app.models import Company, EmailOutbox, EmailStatus
from app.services import email as email_service
from app.services import email_render, email_templates, quotas, suppression

logger = logging.getLogger(__name__)

MAX_ATTEMPTS = 3
RETRY_DELAYS_SECONDS = (60, 300)  # after attempt 1, after attempt 2

# conftest flips this on: queue_email then delivers inline (emulating an
# instant worker) so API tests keep asserting against monkeypatched senders
EAGER_DELIVERY_FOR_TESTS = False

# Registry of queueable senders, by attribute name so monkeypatching
# email_service in tests keeps working. The worker's own scheduled jobs
# (interview reminder, quiz nudge) stay direct - they are already queued
# and self-validating.
SENDER_NAMES: dict[str, str] = {
    "application_received": "send_application_received",
    "quiz_invite": "send_quiz_invite",
    "quiz_reminder": "send_quiz_reminder",
    "stage_advance": "send_stage_advance",
    "rejection": "send_rejection",
    "message": "send_message",
    "team_invite": "send_team_invite",
    "google_linked": "send_google_linked",
    "interview_invite": "send_interview_invite",
    "interview_confirmed": "send_interview_confirmed",
    "interview_scheduled": "send_interview_scheduled",
    "interview_cancelled": "send_interview_cancelled",
    "interview_cancelled_interviewer": "send_interview_cancelled_interviewer",
    "password_reset": "send_password_reset",
    "email_verification": "send_email_verification",
    "scorecard_request": "send_scorecard_request",
    "scorecard_reminder": "send_scorecard_reminder",
}


def _serialize(kwargs: dict[str, Any]) -> dict[str, Any]:
    return {k: {"$dt": v.isoformat()} if isinstance(v, datetime) else v for k, v in kwargs.items()}


def _deserialize(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        k: datetime.fromisoformat(v["$dt"])
        if isinstance(v, dict) and set(v.keys()) == {"$dt"}
        else v
        for k, v in payload.items()
    }


async def queue_email(
    db: AsyncSession,
    *,
    kind: str,
    company_id: uuid.UUID,
    application_id: uuid.UUID | None = None,
    **kwargs: Any,
) -> EmailOutbox | None:
    """Persist the email and hand it to the worker. Commits. Returns None
    on a demo instance, where nothing is ever mailed.

    The commit makes the row durable BEFORE the enqueue attempt: if redis
    is down the sweeper picks it up, so the mail can be late but not lost.
    """
    if kind not in SENDER_NAMES:  # pragma: no cover - programmer error
        raise ValueError(f"unknown email kind {kind!r}")
    if settings.demo_mode:
        # demo addresses are fictional; no row, no counter, no job
        logger.info("demo mode: dropped %s email", kind)
        return None
    if kind in email_render.KINDS and "template_subject" not in kwargs:
        # the chosen (or default) template travels as a snapshot so a later
        # edit or delete never changes an in-flight mail (PR 3)
        resolved_id, template = await email_templates.resolve(
            db, company_id, kind, kwargs.pop("template_id", None)
        )
        kwargs["template_id"] = str(resolved_id) if resolved_id is not None else None
        kwargs["template_subject"] = template.subject
        kwargs["template_body"] = template.body
    row = EmailOutbox(
        company_id=company_id,
        application_id=application_id,
        kind=kind,
        payload=_serialize(kwargs),
    )
    db.add(row)
    await db.commit()
    # per-tenant daily counter (GET /company/usage); the public apply and
    # reissue endpoints pre-check it and answer 429 at the limit
    await quotas.count(Company(id=company_id), quotas.EMAILS)
    if EAGER_DELIVERY_FOR_TESTS:
        skip = await suppressed_for(db, row)
        if skip is not None:
            row.status = EmailStatus.SUPPRESSED
            row.last_error = skip
            await db.commit()
            return row
        try:
            dispatch(row)
        except Exception:  # noqa: BLE001 - mirrors the old BackgroundTasks swallow
            logger.warning("eager outbox delivery failed (kind=%s)", kind, exc_info=True)
        else:
            row.status = EmailStatus.SENT
            row.sent_at = datetime.now(UTC)
            await db.commit()
        return row
    await queue.enqueue("deliver_email", str(row.id), job_id=f"email-{row.id}")
    return row


async def suppressed_for(db: AsyncSession, row: EmailOutbox) -> str | None:
    """The skip reason when the row's recipient is on the suppression list
    (card A7): bounced or complaining addresses get no further mail."""
    to = row.payload.get("to")
    if not isinstance(to, str) or not to:
        return None
    entry = await suppression.lookup(db, to)
    return suppression.skip_message(entry) if entry is not None else None


# payload keys whose value is a candidate capability URL (a signed token
# that opens the assessment, the status page or the booking page)
CAPABILITY_URL_KEYS: tuple[str, ...] = ("quiz_url", "status_url", "booking_url")


def mask_capability_links(text: str, payload: dict[str, Any]) -> str:
    """The stored rendering is for the team to read, never a capability:
    every candidate link in ``payload`` is replaced by its placeholder form
    (the same shape the preview endpoint shows), the mail itself untouched."""
    for key in CAPABILITY_URL_KEYS:
        url = payload.get(key)
        if isinstance(url, str) and url:
            masked = url.rsplit("/", 1)[0] + "/" + email_templates.PREVIEW_LINK_PLACEHOLDER
            text = text.replace(url, masked)
    return text


def dispatch(row: EmailOutbox) -> None:
    """Actually send one outbox row (sync transport). Raises on transport errors."""
    sender: Callable[..., None] = getattr(email_service, SENDER_NAMES[row.kind])
    token = email_service.current_outbox_id.set(str(row.id))
    rendered_token = email_service.last_rendered.set(None)
    try:
        sender(**_deserialize(row.payload))
    finally:
        # keep what the sender rendered even when the transport failed: the
        # timeline shows the attempted mail next to its state (PR 4)
        rendered = email_service.last_rendered.get()
        if rendered is not None:
            subject, text = rendered
            row.rendered_subject = mask_capability_links(subject, row.payload)
            row.rendered_text = mask_capability_links(text, row.payload)
        email_service.last_rendered.reset(rendered_token)
        email_service.current_outbox_id.reset(token)


async def stuck_rows(
    db: AsyncSession, *, older_than: datetime, limit: int = 200
) -> list[uuid.UUID]:
    """Queued rows whose enqueue was lost (redis down at queue time)."""
    return list(
        (
            await db.execute(
                select(EmailOutbox.id)
                .where(
                    EmailOutbox.status == EmailStatus.QUEUED, EmailOutbox.created_at < older_than
                )
                .order_by(EmailOutbox.created_at)
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )
