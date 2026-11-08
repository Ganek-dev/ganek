"""Operator plane (board card "Operator plane", first slice): tenant list,
suspend and unsuspend. Every route sits behind core.ops.require_superadmin;
anyone not on the allow-list gets a 404, as if the routes did not exist."""

import uuid

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.deps import DbSession
from app.core.ops import require_superadmin
from app.models import Company
from app.schemas.ops import OpsTenantOut, SuspendRequest
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
