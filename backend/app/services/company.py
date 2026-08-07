from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Company
from app.schemas.company import BrandingUpdate


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
