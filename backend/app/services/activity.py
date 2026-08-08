"""Tenant activity feed (dashboard 06).

record() only stages the row — it joins the caller's transaction and
commits with it, so a rolled-back action never leaves a phantom event.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ActivityLog, Company

APPLICATION_RECEIVED = "application.received"
QUIZ_FINISHED = "quiz.finished"
STAGE_CHANGED = "stage.changed"
QUIZ_REISSUED = "quiz.reissued"
INTERVIEW_REQUESTED = "interview.requested"
INTERVIEW_BOOKED = "interview.booked"
INTERVIEW_CANCELLED = "interview.cancelled"


def record(
    db: AsyncSession,
    *,
    company_id: uuid.UUID,
    type: str,
    actor_user_id: uuid.UUID | None = None,
    application_id: uuid.UUID | None = None,
    payload: dict[str, object] | None = None,
) -> None:
    db.add(
        ActivityLog(
            company_id=company_id,
            actor_user_id=actor_user_id,
            application_id=application_id,
            type=type,
            payload=payload or {},
        )
    )


async def list_recent(db: AsyncSession, company: Company, *, limit: int) -> list[ActivityLog]:
    return list(
        (
            await db.execute(
                select(ActivityLog)
                .where(ActivityLog.company_id == company.id)
                .order_by(ActivityLog.created_at.desc())
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )
