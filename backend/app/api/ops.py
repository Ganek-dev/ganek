"""Operator plane (board card "Operator plane"): tenant list, suspend,
unsuspend and export. Every route sits behind core.ops.require_superadmin;
anyone not on the allow-list gets a 404, as if the routes did not exist."""

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.deps import DbSession
from app.core.ops import require_superadmin
from app.models import Company
from app.schemas.ops import (
    OpsExportJob,
    OpsExportUser,
    OpsTenantExport,
    OpsTenantOut,
    SuspendRequest,
)
from app.services import ops as ops_service

router = APIRouter(prefix="/ops", tags=["ops"], dependencies=[Depends(require_superadmin)])


def _out(row: ops_service.TenantRow) -> OpsTenantOut:
    c = row.company
    return OpsTenantOut(
        id=c.id,
        slug=c.slug,
        name=c.name,
        created_at=c.created_at,
        suspended_at=c.suspended_at,
        suspension_reason=c.suspension_reason,
        users=row.users,
        jobs=row.jobs,
    )


async def _tenant(db: DbSession, company_id: uuid.UUID) -> Company:
    company = await ops_service.get_tenant(db, company_id)
    if company is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tenant not found")
    return company


@router.get("/tenants", response_model=list[OpsTenantOut])
async def list_tenants(db: DbSession) -> list[OpsTenantOut]:
    return [_out(row) for row in await ops_service.list_tenants(db)]


@router.post("/tenants/{company_id}/suspend", response_model=OpsTenantOut)
async def suspend_tenant(
    company_id: uuid.UUID, payload: SuspendRequest, db: DbSession
) -> OpsTenantOut:
    company = await _tenant(db, company_id)
    await ops_service.suspend(db, company, reason=payload.reason)
    return _out(await ops_service.counts(db, company))


@router.post("/tenants/{company_id}/unsuspend", response_model=OpsTenantOut)
async def unsuspend_tenant(company_id: uuid.UUID, db: DbSession) -> OpsTenantOut:
    company = await _tenant(db, company_id)
    await ops_service.unsuspend(db, company)
    return _out(await ops_service.counts(db, company))


@router.get("/tenants/{company_id}/export", response_model=OpsTenantExport)
async def export_tenant(company_id: uuid.UUID, db: DbSession) -> OpsTenantExport:
    """The whole tenant as JSON: users, jobs and one DSAR-shaped bundle per
    candidate. CV links in the bundles are short-lived presigned URLs."""
    company = await _tenant(db, company_id)
    data = await ops_service.export(db, company)
    return OpsTenantExport(
        generated_at=datetime.now(UTC),
        tenant=_out(await ops_service.counts(db, company)),
        users=[
            OpsExportUser(
                email=u.email,
                display_name=u.display_name,
                role=u.role.value,
                is_active=u.is_active,
                created_at=u.created_at,
                last_login_at=u.last_login_at,
            )
            for u in data.users
        ],
        jobs=[
            OpsExportJob(
                slug=j.slug,
                title=j.title,
                status=j.status.value,
                department=j.department,
                location=j.location,
                remote_policy=j.remote_policy.value,
                employment_type=j.employment_type.value,
                description_md=j.description_md,
                created_at=j.created_at,
                published_at=j.published_at,
                closed_at=j.closed_at,
            )
            for j in data.jobs
        ],
        candidates=data.candidates,
    )
