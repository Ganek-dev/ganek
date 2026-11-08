from fastapi import APIRouter, HTTPException, UploadFile, status

from app.api.deps import AdminUser, CurrentCompany, CurrentUser, DbSession, StaffCompany
from app.core import plans, urls
from app.models import Company, UserRole
from app.schemas.company import (
    BrandingUpdate,
    CompanyOut,
    CompanySettingsUpdate,
    CompanySummary,
    CustomDomainIn,
    CustomDomainOut,
    PlanLimitsOut,
    PlanOut,
    UsageOut,
)
from app.services import company as company_service
from app.services import custom_domains, quotas, storage
from app.services import email as email_service

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
        return CompanySummary(
            slug=company.slug,
            name=company.name,
            careers_domain=urls.custom_careers_domain(company),
        )
    return company


@router.get("/usage", response_model=UsageOut)
async def get_usage(db: DbSession, company: StaffCompany, _admin: AdminUser) -> UsageOut:
    """Abuse-guard counters for the admin banner (STRATEGY §8)."""
    return UsageOut(**await quotas.usage(db, company))


@router.get("/plan", response_model=PlanOut)
async def get_plan(db: DbSession, company: StaffCompany) -> PlanOut:
    """The company's plan, its limits and the live job count (card B1b).
    Admins and recruiters both publish, so both may read it; the frontend
    shows the upgrade link to admins only (Q14)."""
    policy = plans.get_plan_policy()
    limits = policy.limits(company)
    live = await quotas.active_jobs(db, company)
    return PlanOut(
        plan=company.plan.value,
        billing_enabled=policy.billing_enabled,
        limits=PlanLimitsOut(max_live_jobs=limits.max_live_jobs),
        live_jobs=live,
        over_limit=limits.max_live_jobs is not None and live > limits.max_live_jobs,
        upgrade_url=policy.upgrade_url(company),
        trial_ends_at=policy.trial_ends_at(company),
    )


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


def _domain_out(company: Company) -> CustomDomainOut:
    policy = plans.get_plan_policy()
    available = policy.custom_domains(company)
    state = custom_domains.status(company)
    domain, token = company.custom_domain, company.custom_domain_token
    show_txt = state == "pending" and domain is not None and token is not None
    return CustomDomainOut(
        available=available,
        upgrade_url=None if available else policy.upgrade_url(company),
        domain=domain,
        status=state,
        txt_name=custom_domains.txt_record_name(domain) if show_txt and domain else None,
        txt_value=custom_domains.txt_record_value(token) if show_txt and token else None,
        verified_at=company.custom_domain_verified_at,
    )


def _require_custom_domains(company: Company) -> None:
    policy = plans.get_plan_policy()
    if not policy.custom_domains(company):
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail={
                "code": "plan_feature",
                "upgrade_url": policy.upgrade_url(company),
                "message": "Custom domains are not part of your plan.",
            },
        )


@router.get("/domain", response_model=CustomDomainOut)
async def get_custom_domain(company: StaffCompany, _admin: AdminUser) -> CustomDomainOut:
    return _domain_out(company)


@router.put("/domain", response_model=CustomDomainOut)
async def set_custom_domain(
    payload: CustomDomainIn, db: DbSession, company: StaffCompany, _admin: AdminUser
) -> CustomDomainOut:
    """Claim a custom careers domain: a new or changed domain starts pending
    with a fresh TXT token and never routes until verified."""
    _require_custom_domains(company)
    try:
        company = await custom_domains.set_domain(db, company, payload.domain)
    except custom_domains.InvalidDomain as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=exc.reason
        ) from None
    return _domain_out(company)


@router.post("/domain/verify", response_model=CustomDomainOut)
async def verify_custom_domain(
    db: DbSession, company: StaffCompany, _admin: AdminUser
) -> CustomDomainOut:
    _require_custom_domains(company)
    try:
        company = await custom_domains.verify_domain(db, company)
    except custom_domains.VerificationFailed as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=exc.reason) from None
    except custom_domains.DomainTaken:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This domain is already connected to another workspace",
        ) from None
    return _domain_out(company)


@router.delete("/domain", response_model=CustomDomainOut)
async def remove_custom_domain(
    db: DbSession, company: StaffCompany, _admin: AdminUser
) -> CustomDomainOut:
    """Always allowed, also after a downgrade: removing never needs the plan."""
    return _domain_out(await custom_domains.remove_domain(db, company))


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
