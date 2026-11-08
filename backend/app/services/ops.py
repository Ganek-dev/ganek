"""Operator plane services: the cross-tenant reads and writes behind /ops.

Only api/ops.py calls these, behind core.ops.require_superadmin. Every
state change the tenant should know about also lands in the tenant's own
activity feed, with no operator identity (the actor stays empty).
"""

import logging
import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import BillingAccount, Candidate, Company, CompanyPlan, Job, User
from app.schemas.dsar import DsarBundle
from app.services import activity, dsar, erasure

logger = logging.getLogger("app.ops")


class TenantRow:
    def __init__(self, company: Company, users: int, jobs: int) -> None:
        self.company = company
        self.users = users
        self.jobs = jobs


async def list_tenants(db: AsyncSession) -> list[TenantRow]:
    users = select(User.company_id, func.count().label("n")).group_by(User.company_id).subquery()
    jobs = select(Job.company_id, func.count().label("n")).group_by(Job.company_id).subquery()
    rows = await db.execute(
        select(Company, func.coalesce(users.c.n, 0), func.coalesce(jobs.c.n, 0))
        .outerjoin(users, users.c.company_id == Company.id)
        .outerjoin(jobs, jobs.c.company_id == Company.id)
        .order_by(Company.created_at.desc())
    )
    return [TenantRow(company, int(u), int(j)) for company, u, j in rows.all()]


async def get_tenant(db: AsyncSession, company_id: uuid.UUID) -> Company | None:
    return await db.get(Company, company_id)


async def counts(db: AsyncSession, company: Company) -> TenantRow:
    users = await db.scalar(select(func.count(User.id)).where(User.company_id == company.id))
    jobs = await db.scalar(select(func.count(Job.id)).where(Job.company_id == company.id))
    return TenantRow(company, int(users or 0), int(jobs or 0))


async def suspend(db: AsyncSession, company: Company, *, reason: str) -> None:
    """Suspend, or change the reason of a suspension already in place."""
    reason = reason.strip()
    if company.suspended_at is None:
        company.suspended_at = datetime.now(UTC)
    company.suspension_reason = reason
    activity.record(
        db, company_id=company.id, type=activity.TENANT_SUSPENDED, payload={"reason": reason}
    )
    await db.commit()


async def unsuspend(db: AsyncSession, company: Company) -> None:
    if company.suspended_at is None:
        return
    company.suspended_at = None
    company.suspension_reason = None
    activity.record(db, company_id=company.id, type=activity.TENANT_UNSUSPENDED)
    await db.commit()


async def set_plan_override(
    db: AsyncSession, company: Company, *, plan: CompanyPlan | None, end_trial: bool
) -> None:
    """Set (``plan``) or clear (None) the operator plan override, and with
    ``end_trial`` end a running trial now. Ending keeps ``trial_ends_at``
    set, so the trial cannot be started again (card B1d). Only the local
    plan changes: nothing is written to Stripe, and the webhook never
    touches the override. A change lands in the tenant's activity feed and
    the operator log; a call that changes nothing records nothing."""
    row = await db.scalar(
        select(BillingAccount).where(BillingAccount.company_id == company.id).with_for_update()
    )
    if row is None:
        if plan is None:
            return  # no row means no override and no trial to end
        row = BillingAccount(company_id=company.id)
        db.add(row)
    previous = row.plan_override
    now = datetime.now(UTC)
    trial_ended = end_trial and row.trial_ends_at is not None and row.trial_ends_at > now
    if previous == plan and not trial_ended:
        return  # nothing changes; the request's session ends the transaction
    row.plan_override = plan
    if trial_ended:
        row.trial_ends_at = now
    activity.record(
        db,
        company_id=company.id,
        type=activity.TENANT_PLAN_OVERRIDDEN,
        payload={
            "plan": plan.value if plan is not None else None,
            "previous": previous.value if previous is not None else None,
            "trial_ended": trial_ended,
        },
    )
    await db.commit()
    logger.info(
        "ops plan override company=%s plan=%s previous=%s trial_ended=%s",
        company.id,
        plan.value if plan is not None else None,
        previous.value if previous is not None else None,
        trial_ended,
    )
    # the relationship is viewonly and eager: reload it for the response
    await db.refresh(company, attribute_names=["billing_account"])


class TenantExport:
    def __init__(self, users: list[User], jobs: list[Job], candidates: list[DsarBundle]) -> None:
        self.users = users
        self.jobs = jobs
        self.candidates = candidates


async def export(db: AsyncSession, company: Company) -> TenantExport:
    """Everything the tenant owns, for an export on request. Candidates go
    through the DSAR bundle builder, so the export carries exactly what an
    Article 15 bundle carries (and scrubs what it scrubs). The tenant's own
    activity feed records the export, without the operator's identity."""
    users = list(
        (
            await db.execute(
                select(User).where(User.company_id == company.id).order_by(User.created_at)
            )
        )
        .scalars()
        .all()
    )
    jobs = list(
        (await db.execute(select(Job).where(Job.company_id == company.id).order_by(Job.created_at)))
        .scalars()
        .all()
    )
    candidate_ids = (
        (
            await db.execute(
                select(Candidate.id)
                .where(Candidate.company_id == company.id)
                .order_by(Candidate.created_at, Candidate.id)
            )
        )
        .scalars()
        .all()
    )
    candidates: list[DsarBundle] = []
    for candidate_id in candidate_ids:
        bundle = await dsar.export_candidate(db, company, candidate_id)
        if bundle is not None:
            candidates.append(bundle)
    activity.record(db, company_id=company.id, type=activity.TENANT_EXPORTED)
    await db.commit()
    return TenantExport(users, jobs, candidates)


async def delete_tenant(db: AsyncSession, company: Company) -> erasure.TenantPurgeSummary:
    """Delete the tenant and everything it owns (erasure cascade, CVs and
    logo first, fail-closed), leaving blind tombstones so a restored backup
    deletes it again. The router has already checked the guards (suspended
    first, slug typed back, not the operator's own tenant). Nothing lands
    in an activity feed (there is none left); the operator log keeps a
    count-only line."""
    company_id, slug = company.id, company.slug
    summary = await erasure.purge_tenant(db, company_id)
    await db.commit()
    logger.info(
        "ops tenant deleted company=%s slug=%s users=%s jobs=%s candidates=%s "
        "applications=%s storage_objects=%s",
        company_id,
        slug,
        summary.users,
        summary.jobs,
        summary.candidates,
        summary.applications,
        summary.storage_objects,
    )
    return summary
