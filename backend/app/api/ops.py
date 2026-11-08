"""Operator plane (board card "Operator plane"): tenant list, suspend,
unsuspend, export, delete, the plan override and read-only impersonation. Every route sits behind
core.ops.require_superadmin; anyone not on the allow-list gets a 404, as if
the routes did not exist."""

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status

from app.api.deps import DbSession
from app.core.config import settings
from app.core.ops import Superadmin, require_superadmin
from app.core.security import (
    IMPERSONATION_COOKIE_NAME,
    IMPERSONATION_MAX_AGE_SECONDS,
    create_impersonation_token,
    read_impersonation_token,
)
from app.models import Company, CompanyPlan, User
from app.schemas.ops import (
    DeleteTenantRequest,
    ImpersonateRequest,
    OpsExportJob,
    OpsExportUser,
    OpsImpersonationOut,
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


@router.post("/tenants/{company_id}/impersonate", response_model=OpsImpersonationOut)
async def impersonate(
    company_id: uuid.UUID,
    payload: ImpersonateRequest,
    response: Response,
    db: DbSession,
    operator: Superadmin,
) -> OpsImpersonationOut:
    """See the admin app as a tenant user, without their password: a second
    cookie, bound to this operator's session, that lasts one hour and only
    allows reads. The tenant's activity feed records it (as whom, until
    when) and the admin shell shows a banner the whole time."""
    company = await _tenant(db, company_id)
    if company.suspended_at is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Unsuspend the tenant first: its users cannot use the admin app",
        )
    try:
        user = await ops_service.impersonation_target(db, company, payload.user_id)
    except ops_service.ImpersonationTargetError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from None
    token = create_impersonation_token(
        operator.id, operator.token_version, user.id, user.token_version
    )
    claim = read_impersonation_token(token)
    assert claim is not None  # just signed
    response.set_cookie(
        IMPERSONATION_COOKIE_NAME,
        token,
        max_age=IMPERSONATION_MAX_AGE_SECONDS,
        httponly=True,
        samesite="lax",
        secure=settings.cookie_secure,
    )
    await ops_service.start_impersonation(db, company, user, expires_at=claim.expires_at)
    return OpsImpersonationOut(
        user_id=user.id, email=user.email, role=user.role.value, expires_at=claim.expires_at
    )


@router.delete("/impersonation", status_code=status.HTTP_204_NO_CONTENT)
async def end_impersonation(
    request: Request, response: Response, db: DbSession, operator: Superadmin
) -> None:
    """End the impersonation early. Idempotent: with no live cookie it only
    clears whatever is left of it; an expired one already ended on its own."""
    token = request.cookies.get(IMPERSONATION_COOKIE_NAME)
    claim = read_impersonation_token(token) if token else None
    response.delete_cookie(IMPERSONATION_COOKIE_NAME)
    if claim is None or claim.operator_id != operator.id:
        return
    user = await db.get(User, claim.user_id)
    if user is not None:
        await ops_service.end_impersonation(db, user)
