"""Operator plane services: the cross-tenant reads and writes behind /ops.

Only api/ops.py calls these, behind core.ops.require_superadmin. Every
state change the tenant should know about also lands in the tenant's own
activity feed, with no operator identity (the actor stays empty).
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Candidate, Company, Job, User
from app.schemas.dsar import DsarBundle
from app.services import activity, dsar


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
