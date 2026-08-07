from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class CompanyOut(BaseModel):
    """Admin view of the company (branding settings, screen 10)."""

    model_config = ConfigDict(from_attributes=True)

    slug: str
    name: str
    description: str
    logo_url: str | None
    website: str | None
    socials: dict[str, Any]
    theme: dict[str, Any]
    settings: dict[str, Any]


class BrandingUpdate(BaseModel):
    """Branding-only patch; omitted fields stay untouched, null resets.

    Logo upload arrives with its own storage flow in a follow-up — the
    theme keys here are what candidate surfaces consume today.
    """

    primary_color: str | None = Field(default=None, pattern=r"^#[0-9a-fA-F]{6}$")
    radius: Literal["sharp", "default", "round"] | None = None


class CompanySettingsUpdate(BaseModel):
    """Hiring-behavior settings; omitted fields stay untouched, null resets.

    ``quiz_expired_reissue`` decides what a candidate's expired-link
    request does (27c): 'manual' (default) records it for the team,
    'auto' re-issues a fresh link once without waiting for a recruiter.
    """

    quiz_expired_reissue: Literal["manual", "auto"] | None = None
