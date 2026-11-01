from fastapi import APIRouter, HTTPException, UploadFile, status

from app.api.deps import AdminUser, CurrentCompany, CurrentUser, DbSession, StaffCompany
from app.models import Company, UserRole
from app.schemas.company import (
    BrandingUpdate,
    CompanyOut,
    CompanySettingsUpdate,
    CompanySummary,
    UsageOut,
)
from app.services import company as company_service
from app.services import email as email_service
from app.services import quotas, storage

# branding is admin territory (role legend, screen 12)
router = APIRouter(prefix="/company", tags=["company"])


@router.get("", response_model=CompanyOut)
async def get_company(company: StaffCompany, _admin: AdminUser) -> Company:
    return company


@router.get("/summary", response_model=CompanySummary)
async def get_company_summary(
    company: CurrentCompany, user: CurrentUser
) -> Company | CompanySummary:
    """Slug, name and instance mode for any role: the job overview builds
    the public job URL and the share links from these. The defaults are for
    job editors; preferred screening answers are recruiter criteria, and a
    reviewer judges the same candidates, so a reviewer gets them empty."""
    if user.role is UserRole.REVIEWER:
        return CompanySummary(slug=company.slug, name=company.name)
    return company


@router.get("/usage", response_model=UsageOut)
async def get_usage(db: DbSession, company: StaffCompany, _admin: AdminUser) -> UsageOut:
    """Abuse-guard counters for the admin banner (STRATEGY §8)."""
    return UsageOut(**await quotas.usage(db, company))


@router.patch("/branding", response_model=CompanyOut)
async def update_branding(
    payload: BrandingUpdate, db: DbSession, company: StaffCompany, _admin: AdminUser
) -> Company:
    return await company_service.update_branding(db, company, payload)


@router.patch("/settings", response_model=CompanyOut)
async def update_settings(
    payload: CompanySettingsUpdate, db: DbSession, company: StaffCompany, _admin: AdminUser
) -> Company:
    return await company_service.update_settings(db, company, payload)


@router.post("/logo", response_model=CompanyOut)
async def upload_logo(
    file: UploadFile, db: DbSession, company: StaffCompany, _admin: AdminUser
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
async def remove_logo(db: DbSession, company: StaffCompany, _admin: AdminUser) -> Company:
    return await company_service.remove_logo(db, company)


@router.post("/test-email", response_model=dict[str, bool])
async def send_test_email(company: StaffCompany, admin: AdminUser) -> dict[str, bool]:
    """Prove the email pipe end to end (M5.7 H4). Synchronous ON PURPOSE -
    the admin clicked a button and wants the transport error, not a row
    parked in the outbox."""
    if not email_service.configured():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email is not configured - set the GANEK_SMTP_* variables "
            "(or GANEK_EMAIL_PROVIDER=mailjet with its keys) first",
        )
    try:
        email_service.send_email(
            to=admin.email,
            subject=f"Ganek test email - {company.name}",
            body=(
                "This is the test email from your Ganek settings page.\n"
                "If you can read this, candidate email delivery works.\n"
            ),
            ref=str(admin.id),
        )
    except Exception as exc:  # noqa: BLE001 - the whole point is surfacing it
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail=f"Email send failed: {exc}"
        ) from exc
    return {"sent": True}
