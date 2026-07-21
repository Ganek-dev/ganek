from fastapi import APIRouter, BackgroundTasks, HTTPException, status

from app.api.deps import DbSession, PublicCompany, SingleCompany
from app.core.config import settings
from app.models import Company, Job
from app.schemas.public import (
    ApplicationReceived,
    ApplicationSubmit,
    CvUploadTicket,
    PublicCompanyOut,
    PublicCompanyPage,
    PublicJobDetail,
    PublicJobSummary,
)
from app.services import applications as applications_service
from app.services import email as email_service
from app.services import jobs as jobs_service
from app.services import storage

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


def _upload_ticket(company: Company) -> CvUploadTicket:
    object_key = storage.build_cv_key(company.id)
    return CvUploadTicket(
        upload_url=storage.presign_cv_upload(object_key),
        object_key=object_key,
        content_type=storage.CV_CONTENT_TYPE,
        max_size_mb=settings.cv_max_size_mb,
    )


async def _apply(
    db: DbSession,
    company: Company,
    job_slug: str,
    payload: ApplicationSubmit,
    background: BackgroundTasks,
) -> ApplicationReceived:
    job = await _published_job_or_404(db, company, job_slug)
    try:
        await applications_service.submit_application(db, company, job, payload)
    except applications_service.InvalidCvError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=exc.reason
        ) from None
    except applications_service.AlreadyAppliedError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="You already applied for this position",
        ) from None
    background.add_task(
        email_service.send_application_received,
        to=payload.email,
        candidate_name=payload.name,
        job_title=job.title,
        company_name=company.name,
    )
    return ApplicationReceived()


@router.post("/companies/{slug}/jobs/{job_slug}/apply/upload-url", response_model=CvUploadTicket)
async def company_cv_upload_url(
    company: PublicCompany, job_slug: str, db: DbSession
) -> CvUploadTicket:
    await _published_job_or_404(db, company, job_slug)
    return _upload_ticket(company)


@router.post(
    "/companies/{slug}/jobs/{job_slug}/apply",
    response_model=ApplicationReceived,
    status_code=status.HTTP_201_CREATED,
)
async def company_apply(
    company: PublicCompany,
    job_slug: str,
    payload: ApplicationSubmit,
    db: DbSession,
    background: BackgroundTasks,
) -> ApplicationReceived:
    return await _apply(db, company, job_slug, payload, background)


@router.post("/company/jobs/{job_slug}/apply/upload-url", response_model=CvUploadTicket)
async def single_cv_upload_url(
    company: SingleCompany, job_slug: str, db: DbSession
) -> CvUploadTicket:
    await _published_job_or_404(db, company, job_slug)
    return _upload_ticket(company)


@router.post(
    "/company/jobs/{job_slug}/apply",
    response_model=ApplicationReceived,
    status_code=status.HTTP_201_CREATED,
)
async def single_apply(
    company: SingleCompany,
    job_slug: str,
    payload: ApplicationSubmit,
    db: DbSession,
    background: BackgroundTasks,
) -> ApplicationReceived:
    return await _apply(db, company, job_slug, payload, background)
