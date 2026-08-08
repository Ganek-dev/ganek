from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Company
from app.schemas.company import BrandingUpdate, CompanySettingsUpdate


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
    settings = dict(company.settings or {})
    for field in payload.model_fields_set:
        value = getattr(payload, field)
        if value is None:
            settings.pop(field, None)
        else:
            settings[field] = value
    company.settings = settings
    await db.commit()
    await db.refresh(company)
    return company
