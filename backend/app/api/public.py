from fastapi import APIRouter, HTTPException, status

from app.api.deps import DbSession, PublicCompany, SingleCompany
from app.models import Company, Job
from app.schemas.public import (
    PublicCompanyOut,
    PublicCompanyPage,
    PublicJobDetail,
    PublicJobSummary,
)
from app.services import jobs as jobs_service

router = APIRouter(prefix="/public", tags=["public"])


async def _company_page(db: DbSession, company: Company) -> PublicCompanyPage:
    jobs = await jobs_service.list_published_jobs(db, company)
    return PublicCompanyPage(
        company=PublicCompanyOut.model_validate(company),
        jobs=[PublicJobSummary.model_validate(j) for j in jobs],
    )


async def _published_job_or_404(db: DbSession, company: Company, job_slug: str) -> Job:
    job = await jobs_service.get_published_job(db, company, job_slug)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
    return job


# Multi-tenant routes (hosted): /c/{slug} pages
@router.get("/companies/{slug}", response_model=PublicCompanyPage)
async def company_page(company: PublicCompany, db: DbSession) -> PublicCompanyPage:
    return await _company_page(db, company)


@router.get("/companies/{slug}/jobs/{job_slug}", response_model=PublicJobDetail)
async def company_job(company: PublicCompany, job_slug: str, db: DbSession) -> Job:
    return await _published_job_or_404(db, company, job_slug)


# Single-tenant routes (self-host): the instance's one company at /
@router.get("/company", response_model=PublicCompanyPage)
async def single_company_page(company: SingleCompany, db: DbSession) -> PublicCompanyPage:
    return await _company_page(db, company)


@router.get("/company/jobs/{job_slug}", response_model=PublicJobDetail)
async def single_company_job(company: SingleCompany, job_slug: str, db: DbSession) -> Job:
    return await _published_job_or_404(db, company, job_slug)
