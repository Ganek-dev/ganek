"""Who may open which application: the one place a grant is decided (spec
4.1). A later grant source (per-job hiring teams) is one more union clause in
``granted_application_ids`` and nowhere else."""

import uuid

from sqlalchemy import select, union
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Application, Interview, InterviewStatus, Scorecard, User, UserRole


async def granted_application_ids(db: AsyncSession, user: User) -> set[uuid.UUID]:
    """Applications this user holds a grant on, inside their own company: a
    scorecard row not dismissed (open, submitted and declined keep the grant)
    or an interview with a time they run. Both the row and the application
    must be in the user's company."""
    scorecards = (
        select(Scorecard.application_id)
        .join(Application, Application.id == Scorecard.application_id)
        .where(
            Scorecard.reviewer_user_id == user.id,
            Scorecard.company_id == user.company_id,
            Application.company_id == user.company_id,
            Scorecard.dismissed_at.is_(None),
        )
    )
    interviews = (
        select(Interview.application_id)
        .join(Application, Application.id == Interview.application_id)
        .where(
            Interview.interviewer_user_id == user.id,
            Interview.company_id == user.company_id,
            Application.company_id == user.company_id,
            Interview.status != InterviewStatus.CANCELLED,
            Interview.scheduled_start.is_not(None),
        )
    )
    return set((await db.execute(union(scorecards, interviews))).scalars().all())


async def can_open_application(db: AsyncSession, user: User, application_id: uuid.UUID) -> bool:
    """Admins and members are unrestricted within their company, so the caller
    still loads the application through the tenancy-scoped query."""
    if user.role is not UserRole.REVIEWER:
        return True
    return application_id in await granted_application_ids(db, user)
