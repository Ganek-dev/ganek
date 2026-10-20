"""Suppression list: addresses outbound mail must skip (board card A7).

Fed by provider bounce and complaint webhooks (``api/email_webhooks.py``),
consulted by the outbox before every send. Addresses are stored as blind
hashes only; see ``models/email_suppression.py``.
"""

from __future__ import annotations

import hashlib
import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import EmailOutbox, EmailStatus
from app.models.email_suppression import EmailSuppression

logger = logging.getLogger(__name__)

BOUNCE = "bounce"
COMPLAINT = "complaint"
BLOCKED = "blocked"
UNSUBSCRIBE = "unsubscribe"

# what the outbox row ends up as, per suppression reason
OUTBOX_STATUS_FOR_REASON: dict[str, EmailStatus] = {
    BOUNCE: EmailStatus.BOUNCED,
    BLOCKED: EmailStatus.BOUNCED,
    COMPLAINT: EmailStatus.COMPLAINED,
    UNSUBSCRIBE: EmailStatus.COMPLAINED,
}


def hash_email(email: str) -> str:
    return hashlib.sha256(email.strip().lower().encode()).hexdigest()


@dataclass(frozen=True)
class ProviderEvent:
    """One bounce/complaint-class event, provider format already unwrapped."""

    email: str
    reason: str | None  # None: informational only (soft bounce), never suppresses
    detail: str | None
    outbox_id: str | None


def parse_mailjet(payload: Any) -> list[ProviderEvent]:
    """Mailjet Event API: one event object or an array of them (grouping on).

    Only recipient-side facts suppress: hard bounces, spam complaints,
    Mailjet's own recipient blocks and unsubscribes. Soft bounces annotate
    the outbox row and nothing else; delivery/open/click events are ignored.
    """
    items = payload if isinstance(payload, list) else [payload]
    events: list[ProviderEvent] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        email = item.get("email")
        if not isinstance(email, str) or not email:
            continue
        kind = item.get("event")
        error = item.get("error") or item.get("comment")
        detail = str(error)[:500] if error else None
        custom_id = item.get("CustomID")
        outbox_id = custom_id if isinstance(custom_id, str) and custom_id else None
        if kind == "bounce":
            reason = BOUNCE if item.get("hard_bounce") else None
        elif kind == "spam":
            reason = COMPLAINT
            detail = detail or f"spam complaint via {item.get('source') or 'feedback loop'}"
        elif kind == "blocked":
            related = item.get("error_related_to")
            reason = BLOCKED if related in ("recipient", "domain") else None
        elif kind == "unsub":
            reason = UNSUBSCRIBE
        else:
            continue
        events.append(ProviderEvent(email=email, reason=reason, detail=detail, outbox_id=outbox_id))
    return events


async def lookup(db: AsyncSession, email: str) -> EmailSuppression | None:
    return await db.get(EmailSuppression, hash_email(email))


async def suppress(
    db: AsyncSession,
    *,
    email: str,
    reason: str,
    source: str,
    detail: str | None = None,
    company_id: uuid.UUID | None = None,
) -> EmailSuppression:
    """Insert or refresh the entry. Flushes, does not commit."""
    now = datetime.now(UTC)
    row = await lookup(db, email)
    if row is None:
        row = EmailSuppression(
            email_hash=hash_email(email),
            reason=reason,
            source=source,
            detail=detail,
            company_id=company_id,
            created_at=now,
            last_event_at=now,
        )
        db.add(row)
    else:
        row.reason = reason
        row.source = source
        row.detail = detail
        row.last_event_at = now
        if company_id is not None:
            row.company_id = company_id
    await db.flush()
    return row


def skip_message(row: EmailSuppression) -> str:
    """The outbox row's ``last_error`` when a send is skipped."""
    return f"address suppressed ({row.reason} on {row.last_event_at.date().isoformat()})"


async def apply_events(
    db: AsyncSession, events: list[ProviderEvent], *, source: str
) -> tuple[int, int]:
    """Record provider events: suppress addresses, annotate outbox rows.

    Returns (events handled, addresses suppressed). Commits once.
    """
    suppressed = 0
    for event in events:
        outbox_row: EmailOutbox | None = None
        if event.outbox_id is not None:
            try:
                outbox_row = await db.get(EmailOutbox, uuid.UUID(event.outbox_id))
            except ValueError:
                outbox_row = None
        if event.reason is None:
            if outbox_row is not None and event.detail:
                outbox_row.last_error = f"soft bounce: {event.detail}"[:500]
            continue
        entry = await suppress(
            db,
            email=event.email,
            reason=event.reason,
            source=source,
            detail=event.detail,
            company_id=outbox_row.company_id if outbox_row is not None else None,
        )
        suppressed += 1
        if outbox_row is not None:
            outbox_row.status = OUTBOX_STATUS_FOR_REASON[event.reason]
            outbox_row.last_error = (event.detail or entry.reason)[:500]
    await db.commit()
    if events:
        logger.info(
            "email events from %s: %d handled, %d suppressed", source, len(events), suppressed
        )
    return len(events), suppressed
