from fastapi import APIRouter, HTTPException, UploadFile, status

from app.api.deps import AdminUser, CurrentCompany, DbSession
from app.models import Company
from app.schemas.company import BrandingUpdate, CompanyOut, CompanySettingsUpdate
from app.services import company as company_service
from app.services import storage

# branding is admin territory (role legend, screen 12)
router = APIRouter(prefix="/company", tags=["company"])


@router.get("", response_model=CompanyOut)
async def get_company(company: CurrentCompany, _admin: AdminUser) -> Company:
    return company


@router.patch("/branding", response_model=CompanyOut)
async def update_branding(
    payload: BrandingUpdate, db: DbSession, company: CurrentCompany, _admin: AdminUser
) -> Company:
    return await company_service.update_branding(db, company, payload)


@router.patch("/settings", response_model=CompanyOut)
async def update_settings(
    payload: CompanySettingsUpdate, db: DbSession, company: CurrentCompany, _admin: AdminUser
) -> Company:
    return await company_service.update_settings(db, company, payload)


@router.post("/logo", response_model=CompanyOut)
async def upload_logo(
    file: UploadFile, db: DbSession, company: CurrentCompany, _admin: AdminUser
) -> Company:
    """Branding logo (screen 10). Validated by content, stored in the app
    bucket, served via the public logo endpoint (option B: zero extra
    infra for self-hosters; hosted puts a CDN in front)."""
    data = await file.read(storage.LOGO_MAX_BYTES + 1)
    try:
        return await company_service.set_logo(db, company, data, file.content_type or "")
    except company_service.InvalidLogoError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=exc.reason
        ) from None


@router.delete("/logo", response_model=CompanyOut)
async def remove_logo(db: DbSession, company: CurrentCompany, _admin: AdminUser) -> Company:
    return await company_service.remove_logo(db, company)
