"""Read-access audit trail: who looked at which candidate.

Recorded on detail-level reads only (opening the applicant, the CV
download link, the quiz answers, the DSAR bundle). The list view is
summary-level and stays unlogged. Repeats by the same actor on the same
applicant and action inside ``COLLAPSE_WINDOW`` add no row, so a panel
refresh does not spam the trail.
"""

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AccessLog, ApiKey, Company, User

VIEW = "view"
CV_DOWNLOAD = "cv_download"
QUIZ_ANSWERS = "quiz_answers"
DSAR_EXPORT = "dsar_export"

COLLAPSE_WINDOW = timedelta(minutes=10)


async def record(
    db: AsyncSession,
    *,
    company: Company,
    application_id: uuid.UUID,
    action: str,
    user: User | None = None,
    api_key: ApiKey | None = None,
) -> None:
    """Append one row unless the same actor did the same thing to the same
    applicant inside the collapse window. Commits: reads have no other
    transaction to join."""
    conditions = [
        AccessLog.company_id == company.id,
        AccessLog.application_id == application_id,
        AccessLog.action == action,
        AccessLog.created_at >= datetime.now(UTC) - COLLAPSE_WINDOW,
    ]
    if user is not None:
        conditions.append(AccessLog.actor_user_id == user.id)
    elif api_key is not None:
        conditions.append(AccessLog.api_key_id == api_key.id)
    recent = (await db.execute(select(AccessLog.id).where(*conditions).limit(1))).first()
    if recent is not None:
        return
    db.add(
        AccessLog(
            company_id=company.id,
            application_id=application_id,
            actor_user_id=user.id if user is not None else None,
            api_key_id=api_key.id if api_key is not None else None,
            action=action,
        )
    )
    await db.commit()


async def list_for_application(
    db: AsyncSession, company: Company, application_id: uuid.UUID, *, limit: int = 100
) -> list[AccessLog]:
    return list(
        (
            await db.execute(
                select(AccessLog)
                .where(
                    AccessLog.company_id == company.id,
                    AccessLog.application_id == application_id,
                )
                .order_by(AccessLog.created_at.desc(), AccessLog.id.desc())
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )
