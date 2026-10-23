"""Company-wide read-access log (Settings > Privacy): who looked at which
candidate across the tenant, filtered, paged, and as a CSV file."""

import csv
import io
import uuid
from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, Query, Response

from app.api.deps import AdminUser, CurrentCompany, DbSession
from app.models import AccessLog
from app.schemas.applications import AccessLogPage, AccessLogRowOut
from app.services import access_log, activity

router = APIRouter(prefix="/access-log", tags=["access-log"])


def _row(entry: AccessLog) -> AccessLogRowOut:
    return AccessLogRowOut(
        id=entry.id,
        action=entry.action,
        actor_email=entry.actor_email,
        actor_label=entry.actor_label,
        api_key_name=entry.api_key_name,
        created_at=entry.created_at,
        application_id=entry.application_id,
        candidate_name=entry.application.candidate.name,
        job_title=entry.application.job.title,
    )


@router.get("", response_model=AccessLogPage)
async def list_access_log(
    db: DbSession,
    company: CurrentCompany,
    _admin: AdminUser,
    actor_user_id: uuid.UUID | None = None,
    api_key_id: uuid.UUID | None = None,
    application_id: uuid.UUID | None = None,
    action: str | None = Query(default=None, max_length=30),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> AccessLogPage:
    """Admins only; reading the log is not itself a read of any candidate."""
    filters = access_log.Filters(actor_user_id, api_key_id, application_id, action)
    rows, total = await access_log.list_for_company(
        db, company, filters, limit=limit, offset=offset
    )
    return AccessLogPage(items=[_row(r) for r in rows], total=total)


@router.get("/export")
async def export_access_log(
    db: DbSession,
    company: CurrentCompany,
    admin: AdminUser,
    format: Literal["csv"] = "csv",
    actor_user_id: uuid.UUID | None = None,
    api_key_id: uuid.UUID | None = None,
    application_id: uuid.UUID | None = None,
    action: str | None = Query(default=None, max_length=30),
) -> Response:
    """The current filter as a CSV file, no internal ids. One activity
    entry per export names who pulled how many rows with which filters."""
    filters = access_log.Filters(actor_user_id, api_key_id, application_id, action)
    rows, _ = await access_log.list_for_company(db, company, filters, limit=None)
    activity.record(
        db,
        company_id=company.id,
        type=activity.ACCESS_LOG_EXPORTED,
        actor_user_id=admin.id,
        payload={"rows": len(rows), **filters.as_payload()},
    )
    await db.commit()
    stamp = datetime.now(UTC).date().isoformat()
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=access_log.EXPORT_COLUMNS)
    writer.writeheader()
    writer.writerows(access_log.export_row(r) for r in rows)
    return Response(
        buffer.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="access-log-{company.slug}-{stamp}.csv"'
        },
    )
