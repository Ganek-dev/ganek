"""Email outbox (M5.7 H4): queue-then-deliver replaces fire-and-forget.

The request that decides to email someone writes an ``email_outbox`` row
and enqueues an arq delivery job. Redis being down only delays delivery —
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
from app.models import EmailOutbox, EmailStatus
from app.services import email as email_service

logger = logging.getLogger(__name__)

MAX_ATTEMPTS = 3
RETRY_DELAYS_SECONDS = (60, 300)  # after attempt 1, after attempt 2

# conftest flips this on: queue_email then delivers inline (emulating an
# instant worker) so API tests keep asserting against monkeypatched senders
EAGER_DELIVERY_FOR_TESTS = False

# Registry of queueable senders, by attribute name so monkeypatching
# email_service in tests keeps working. The worker's own scheduled jobs
# (interview reminder, quiz nudge) stay direct — they are already queued
# and self-validating.
SENDER_NAMES: dict[str, str] = {
    "application_received": "send_application_received",
    "quiz_invite": "send_quiz_invite",
    "quiz_reminder": "send_quiz_reminder",
    "stage_advance": "send_stage_advance",
    "rejection": "send_rejection",
    "team_invite": "send_team_invite",
    "google_linked": "send_google_linked",
    "interview_invite": "send_interview_invite",
    "interview_cancelled": "send_interview_cancelled",
    "password_reset": "send_password_reset",
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
) -> EmailOutbox:
    """Persist the email and hand it to the worker. Commits.

    The commit makes the row durable BEFORE the enqueue attempt: if redis
    is down the sweeper picks it up, so the mail can be late but not lost.
    """
    if kind not in SENDER_NAMES:  # pragma: no cover - programmer error
        raise ValueError(f"unknown email kind {kind!r}")
    row = EmailOutbox(
        company_id=company_id,
        application_id=application_id,
        kind=kind,
        payload=_serialize(kwargs),
    )
    db.add(row)
    await db.commit()
    if EAGER_DELIVERY_FOR_TESTS:
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


def dispatch(row: EmailOutbox) -> None:
    """Actually send one outbox row (sync SMTP). Raises on transport errors."""
    sender: Callable[..., None] = getattr(email_service, SENDER_NAMES[row.kind])
    sender(**_deserialize(row.payload))


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
