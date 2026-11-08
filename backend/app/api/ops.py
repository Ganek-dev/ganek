"""Operator plane (board card "Operator plane"): tenant list, suspend,
unsuspend, export, delete and the plan override. Every route sits behind
core.ops.require_superadmin; anyone not on the allow-list gets a 404, as if
the routes did not exist."""

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.deps import DbSession
from app.core.ops import Superadmin, require_superadmin
from app.models import Company, CompanyPlan
from app.schemas.ops import (
    DeleteTenantRequest,
    OpsExportJob,
    OpsExportUser,
    OpsTenantDeleted,
    OpsTenantExport,
    OpsTenantOut,
    PlanOverrideRequest,
    SuspendRequest,
)
from app.services import ops as ops_service
from app.services.erasure import TenantStorageError

router = APIRouter(prefix="/ops", tags=["ops"], dependencies=[Depends(require_superadmin)])


def _out(row: ops_service.TenantRow) -> OpsTenantOut:
    c = row.company
    account = c.billing_account
    return OpsTenantOut(
        id=c.id,
        slug=c.slug,
        name=c.name,
        created_at=c.created_at,
        suspended_at=c.suspended_at,
        suspension_reason=c.suspension_reason,
        plan=c.plan.value,
        plan_override=(
            account.plan_override.value
            if account is not None and account.plan_override is not None
            else None
        ),
        trial_ends_at=account.trial_ends_at if account is not None else None,
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


@router.put("/tenants/{company_id}/plan", response_model=OpsTenantOut)
async def set_plan_override(
    company_id: uuid.UUID, payload: PlanOverrideRequest, db: DbSession
) -> OpsTenantOut:
    """Set or clear the plan override (Q21) and optionally end a running
    trial. Comp accounts, partners and a broken webhook; Stripe is not
    touched. Publish limits follow on the tenant's next request."""
    company = await _tenant(db, company_id)
    plan = CompanyPlan(payload.plan_override) if payload.plan_override is not None else None
    await ops_service.set_plan_override(db, company, plan=plan, end_trial=payload.end_trial)
    return _out(await ops_service.counts(db, company))


@router.delete("/tenants/{company_id}", response_model=OpsTenantDeleted)
async def delete_tenant(
    company_id: uuid.UUID, payload: DeleteTenantRequest, db: DbSession, operator: Superadmin
) -> OpsTenantDeleted:
    """Delete a tenant and everything it owns. Irreversible, so three guards:
    the tenant must be suspended first (its users are already locked out
    and had the reason), the caller types its slug back, and an operator
    cannot delete the workspace their own account lives in. CVs and the
    logo go first; a storage failure leaves the tenant untouched (503)."""
    company = await _tenant(db, company_id)
    if company.suspended_at is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Suspend the tenant before deleting it",
        )
    if payload.confirm_slug.strip() != company.slug:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="confirm_slug does not match the tenant's slug",
        )
    if operator.company_id == company.id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="You cannot delete the workspace your own account belongs to",
        )
    slug = company.slug
    try:
        summary = await ops_service.delete_tenant(db, company)
    except TenantStorageError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Object storage cleanup failed; nothing was deleted, try again",
        ) from exc
    return OpsTenantDeleted(
        id=company_id,
        slug=slug,
        users=summary.users,
        jobs=summary.jobs,
        candidates=summary.candidates,
        applications=summary.applications,
        storage_objects=summary.storage_objects,
    )


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
