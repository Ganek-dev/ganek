import uuid

from fastapi import APIRouter, HTTPException, status

from app.api.deps import CurrentCompany, DbSession
from app.models import Application, ApplicationStage
from app.schemas.applications import ApplicationOut, CvDownload, StageUpdate
from app.services import applications as applications_service
from app.services import storage

router = APIRouter(prefix="/applications", tags=["applications"])


async def _get_or_404(
    db: DbSession, company: CurrentCompany, application_id: uuid.UUID
) -> Application:
    application = await applications_service.get_application(db, company, application_id)
    if application is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Application not found")
    return application


@router.get("", response_model=list[ApplicationOut])
async def list_applications(
    db: DbSession,
    company: CurrentCompany,
    job_id: uuid.UUID | None = None,
    stage: ApplicationStage | None = None,
) -> list[Application]:
    return await applications_service.list_applications(db, company, job_id=job_id, stage=stage)


@router.get("/{application_id}", response_model=ApplicationOut)
async def get_application(
    application_id: uuid.UUID, db: DbSession, company: CurrentCompany
) -> Application:
    return await _get_or_404(db, company, application_id)


@router.patch("/{application_id}/stage", response_model=ApplicationOut)
async def set_stage(
    application_id: uuid.UUID, payload: StageUpdate, db: DbSession, company: CurrentCompany
) -> Application:
    application = await _get_or_404(db, company, application_id)
    return await applications_service.set_stage(db, application, payload.stage)


@router.get("/{application_id}/cv-url", response_model=CvDownload)
async def cv_download_url(
    application_id: uuid.UUID, db: DbSession, company: CurrentCompany
) -> CvDownload:
    application = await _get_or_404(db, company, application_id)
    return CvDownload(
        download_url=storage.presign_cv_download(application.cv_object_key, application.cv_filename)
    )
