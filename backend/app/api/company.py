from fastapi import APIRouter

from app.api.deps import AdminUser, CurrentCompany, DbSession
from app.models import Company
from app.schemas.company import BrandingUpdate, CompanyOut
from app.services import company as company_service

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
