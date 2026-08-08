import time

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models import Company
from app.schemas.company import BrandingUpdate, CompanySettingsUpdate
from app.services import storage


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
            merged[field] = value
    company.settings = merged
    await db.commit()
    await db.refresh(company)
    return company


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
