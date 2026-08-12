import time

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models import Company
from app.schemas.company import BrandingUpdate, CompanySettingsUpdate
from app.schemas.public import PublicPrivacyNotice
from app.services import storage

RETENTION_DEFAULT_MONTHS = 6
"""Post-decision retention window when a company hasn't set one.

Chosen to be defensible in the strictest mainstream EU regimes (Germany ~6
months AGG practice; CNIL caps at 2 years) — see GDPR research notes. The
privacy notice renders this value and the retention purge will enforce it.
"""


class InvalidLogoError(Exception):
    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


async def update_branding(db: AsyncSession, company: Company, payload: BrandingUpdate) -> Company:
    """Merge branding keys into ``theme``: omitted = untouched, null = reset.

    ``theme`` is reassigned (not mutated) so SQLAlchemy sees the JSONB change.
    """
    theme = dict(company.theme or {})
    for field, key in (("primary_color", "primary_color"), ("radius", "radius")):
        if field not in payload.model_fields_set:
            continue
        value = getattr(payload, field)
        if value is None:
            theme.pop(key, None)
        else:
            theme[key] = value
    company.theme = theme
    await db.commit()
    await db.refresh(company)
    return company


async def update_settings(
    db: AsyncSession, company: Company, payload: CompanySettingsUpdate
) -> Company:
    """Merge hiring-behavior keys into ``settings`` (same rules as branding)."""
    merged = dict(company.settings or {})
    for field in payload.model_fields_set:
        value = getattr(payload, field)
        if value is None:
            merged.pop(field, None)
        else:
            if not isinstance(value, (str, int, float, bool)):
                # pydantic types like HttpUrl must land in JSONB as plain strings
                value = str(value)
            merged[field] = value
    company.settings = merged
    await db.commit()
    await db.refresh(company)
    return company


def controller_name(company: Company) -> str:
    """Controller identity for candidate-facing footers: legal name when set."""
    return (company.settings or {}).get("legal_name") or company.name


def privacy_notice_url(company: Company) -> str:
    """Absolute candidate-facing privacy-notice URL (mode-aware, for emails)."""
    base = settings.public_base_url.rstrip("/")
    if settings.mode == "single":
        return f"{base}/privacy"
    return f"{base}/c/{company.slug}/privacy"


def privacy_notice(company: Company) -> PublicPrivacyNotice:
    """Per-company variables for the candidate privacy notice page.

    Fallbacks applied server-side so the page never needs defaults logic;
    internal settings keys (quiz_expired_reissue, …) never serialize here.
    """
    stored = company.settings or {}
    return PublicPrivacyNotice(
        company_name=company.name,
        legal_name=controller_name(company),
        privacy_contact_email=stored.get("privacy_contact_email"),
        retention_months=stored.get("retention_months") or RETENTION_DEFAULT_MONTHS,
        privacy_policy_url=stored.get("privacy_policy_url"),
        brand_primary=(company.theme or {}).get("primary_color"),
        logo_url=company.logo_url,
    )


def sniff_logo(data: bytes, declared_type: str) -> str:
    """Validate a logo upload by content, not extension. Returns the canonical
    content type or raises. SVGs additionally reject embedded scripting —
    the serving endpoint's CSP already blocks execution, this is belt and
    braces for anyone hotlinking the file elsewhere."""
    if len(data) > storage.LOGO_MAX_BYTES:
        raise InvalidLogoError("Logo must be 2 MB or smaller")
    if not data:
        raise InvalidLogoError("Empty file")
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    head = data[:4096].lstrip(b"\xef\xbb\xbf").lstrip()
    if head.startswith((b"<?xml", b"<svg")):
        lowered = data.lower()
        banned = (b"<script", b"javascript:", b"onload=", b"onerror=", b"<foreignobject")
        if any(token in lowered for token in banned):
            raise InvalidLogoError("SVG logos must not contain scripts")
        return "image/svg+xml"
    raise InvalidLogoError(
        f"Unsupported file type (got {declared_type or 'unknown'}); use PNG, JPG, or SVG"
    )


async def set_logo(db: AsyncSession, company: Company, data: bytes, declared_type: str) -> Company:
    """Store the logo and point ``logo_url`` at the public serving endpoint.

    The URL is absolute (Google Jobs JSON-LD needs one) and carries a
    version param so the stable object key still cache-busts on replace.
    """
    content_type = sniff_logo(data, declared_type)
    await storage.put_object(storage.build_logo_key(company.id), data, content_type)
    base = settings.public_base_url.rstrip("/")
    company.logo_url = f"{base}/api/v1/public/companies/{company.slug}/logo?v={int(time.time())}"
    await db.commit()
    await db.refresh(company)
    return company


async def remove_logo(db: AsyncSession, company: Company) -> Company:
    await storage.delete_object(storage.build_logo_key(company.id))
    company.logo_url = None
    await db.commit()
    await db.refresh(company)
    return company
