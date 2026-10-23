"""Read-access audit trail: who looked at which candidate.

Recorded on detail-level reads only (opening the applicant, the CV
download link, the quiz answers, the DSAR bundle). The list view is
summary-level and stays unlogged. Repeats by the same actor on the same
applicant and action inside ``COLLAPSE_WINDOW`` add no row, so a panel
refresh does not spam the trail.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import ColumnElement, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import AccessLog, ApiKey, Application, Company, User

VIEW = "view"
CV_DOWNLOAD = "cv_download"
QUIZ_ANSWERS = "quiz_answers"
DSAR_EXPORT = "dsar_export"

COLLAPSE_WINDOW = timedelta(minutes=10)

EXPORT_COLUMNS = ("when", "actor", "action", "candidate_name", "candidate_email", "job")


@dataclass(frozen=True)
class Filters:
    """Company-wide listing filters; every field optional."""

    actor_user_id: uuid.UUID | None = None
    api_key_id: uuid.UUID | None = None
    application_id: uuid.UUID | None = None
    action: str | None = None

    def as_payload(self) -> dict[str, object]:
        return {
            "actor_user_id": str(self.actor_user_id) if self.actor_user_id else None,
            "api_key_id": str(self.api_key_id) if self.api_key_id else None,
            "application_id": str(self.application_id) if self.application_id else None,
            "action": self.action,
        }


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


def _company_conditions(company: Company, filters: Filters) -> list[ColumnElement[bool]]:
    conditions: list[ColumnElement[bool]] = [AccessLog.company_id == company.id]
    if filters.actor_user_id is not None:
        conditions.append(AccessLog.actor_user_id == filters.actor_user_id)
    if filters.api_key_id is not None:
        conditions.append(AccessLog.api_key_id == filters.api_key_id)
    if filters.application_id is not None:
        conditions.append(AccessLog.application_id == filters.application_id)
    if filters.action is not None:
        conditions.append(AccessLog.action == filters.action)
    return conditions


async def list_for_company(
    db: AsyncSession,
    company: Company,
    filters: Filters,
    *,
    limit: int | None = 50,
    offset: int = 0,
) -> tuple[list[AccessLog], int]:
    """Company-wide trail, newest first, with the candidate and job loaded.
    ``limit=None`` returns everything (export)."""
    conditions = _company_conditions(company, filters)
    total = (
        await db.execute(select(func.count()).select_from(AccessLog).where(*conditions))
    ).scalar_one()
    query = (
        select(AccessLog)
        .where(*conditions)
        .options(
            selectinload(AccessLog.application).selectinload(Application.candidate),
            selectinload(AccessLog.application).selectinload(Application.job),
        )
        .order_by(AccessLog.created_at.desc(), AccessLog.id.desc())
        .offset(offset)
    )
    if limit is not None:
        query = query.limit(limit)
    rows = list((await db.execute(query)).scalars().all())
    return rows, int(total)


def actor_name(row: AccessLog) -> str:
    """Who, for files and labels: the key's name, else the teammate's email
    (a tombstoned teammate keeps the placeholder address)."""
    if row.api_key is not None:
        return f"API key {row.api_key.name}"
    return row.actor_email or "removed teammate"


def export_row(row: AccessLog) -> dict[str, str]:
    """One flat, spreadsheet-shaped line. No internal ids: the candidate email
    is the join key, like the applicant export."""
    return {
        "when": row.created_at.isoformat(),
        "actor": actor_name(row),
        "action": row.action,
        "candidate_name": row.application.candidate.name,
        "candidate_email": row.application.candidate.email,
        "job": row.application.job.title,
    }


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
