"""Scheduled mails: a rejection held back by `send_after`.

A row is `scheduled` from the moment staff reject with a delay until the
worker releases it at `send_after`. Until then it can be cancelled: by staff
through the cancel route, or automatically when the application leaves the
rejected stage (the undo toast, a manual stage move, bulk-stage). The automatic
path also takes a released row waiting for a retry (`queued` with send_after
set); the staff route stays scheduled-only. A cancelled row is never sent and
stays visible on the delivery trail.

Cancels lock the row (FOR UPDATE), the same lock `deliver_email` takes, so a
cancel racing a release either wins or sees the row is no longer scheduled.
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ActivityLog, Application, ApplicationStage, EmailOutbox, EmailStatus
from app.services import activity

REJECTION_KIND = "rejection"


class NotScheduled(Exception):
    """The row is no longer scheduled (sent, cancelled, released...)."""


def _cancel_row(db: AsyncSession, row: EmailOutbox, *, actor_user_id: uuid.UUID | None) -> None:
    """Stage the status change and the activity entry; the caller commits."""
    row.status = EmailStatus.CANCELLED
    row.cancelled_at = datetime.now(UTC)
    activity.record(
        db,
        company_id=row.company_id,
        type=activity.EMAIL_CANCELLED,
        actor_user_id=actor_user_id,
        application_id=row.application_id,
        payload={"email_id": str(row.id), "kind": row.kind},
    )


async def cancel(
    db: AsyncSession, *, row: EmailOutbox, actor_user_id: uuid.UUID | None
) -> EmailOutbox:
    """Cancel one scheduled mail. Re-reads the row FOR UPDATE so a concurrent
    release is seen; raises NotScheduled when it is no longer scheduled."""
    await db.refresh(row, with_for_update=True)
    if row.status is not EmailStatus.SCHEDULED:
        await db.rollback()
        raise NotScheduled
    _cancel_row(db, row, actor_user_id=actor_user_id)
    await db.commit()
    await db.refresh(row)
    return row


async def cancel_locked(
    db: AsyncSession, *, row: EmailOutbox, actor_user_id: uuid.UUID | None
) -> None:
    """Cancel a row the caller already holds FOR UPDATE, whatever its hold
    state (the worker's stage guard). Commits."""
    _cancel_row(db, row, actor_user_id=actor_user_id)
    await db.commit()


async def cancel_for_application(
    db: AsyncSession, *, application: Application, actor_user_id: uuid.UUID | None
) -> int:
    """Cancel every held rejection mail of this application in one commit:
    scheduled rows, and released rows waiting for a retry (`queued` with
    send_after set). A rejection queued immediately (no send_after) or already
    sent is skipped. Returns the count."""
    rows = (
        (
            await db.execute(
                select(EmailOutbox)
                .where(
                    EmailOutbox.company_id == application.company_id,
                    EmailOutbox.application_id == application.id,
                    EmailOutbox.kind == REJECTION_KIND,
                    or_(
                        EmailOutbox.status == EmailStatus.SCHEDULED,
                        and_(
                            EmailOutbox.status == EmailStatus.QUEUED,
                            EmailOutbox.send_after.is_not(None),
                        ),
                    ),
                )
                .with_for_update()
            )
        )
        .scalars()
        .all()
    )
    for row in rows:
        _cancel_row(db, row, actor_user_id=actor_user_id)
    if rows:
        await db.commit()
    return len(rows)


async def scheduled_rejection(db: AsyncSession, application: Application) -> EmailOutbox | None:
    """The newest scheduled rejection mail of this application, if any."""
    return (
        await db.execute(
            select(EmailOutbox)
            .where(
                EmailOutbox.company_id == application.company_id,
                EmailOutbox.application_id == application.id,
                EmailOutbox.kind == REJECTION_KIND,
                EmailOutbox.status == EmailStatus.SCHEDULED,
            )
            .order_by(EmailOutbox.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()


async def rejection_queued_or_sent(db: AsyncSession, application: Application) -> bool:
    """Whether a rejection mail of this application is on its way or went out."""
    found = await db.scalar(
        select(EmailOutbox.id)
        .where(
            EmailOutbox.company_id == application.company_id,
            EmailOutbox.application_id == application.id,
            EmailOutbox.kind == REJECTION_KIND,
            EmailOutbox.status.in_([EmailStatus.QUEUED, EmailStatus.SENT]),
        )
        .limit(1)
    )
    return found is not None


async def stage_before_rejection(db: AsyncSession, application: Application) -> str:
    """The stage the application was in before its latest move to rejected
    (where an undo returns it); `screening` when the log has no such move."""
    entry = (
        await db.execute(
            select(ActivityLog)
            .where(
                ActivityLog.company_id == application.company_id,
                ActivityLog.application_id == application.id,
                ActivityLog.type == activity.STAGE_CHANGED,
                ActivityLog.payload["to"].astext == ApplicationStage.REJECTED.value,
            )
            .order_by(ActivityLog.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if entry is None:
        return ApplicationStage.SCREENING.value
    return str(entry.payload.get("from", ApplicationStage.SCREENING.value))
