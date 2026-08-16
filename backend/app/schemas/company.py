from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, HttpUrl

from app.core.config import settings as app_settings


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
    # not a column — the instance's deployment mode, so admin surfaces can
    # render the real careers URL (single mode serves it at the root)
    mode: Literal["single", "multi"] = Field(default_factory=lambda: app_settings.mode)


class BrandingUpdate(BaseModel):
    """Branding-only patch; omitted fields stay untouched, null resets.

    Logo upload arrives with its own storage flow in a follow-up — the
    theme keys here are what candidate surfaces consume today.
    """

    primary_color: str | None = Field(default=None, pattern=r"^#[0-9a-fA-F]{6}$")
    radius: Literal["sharp", "default", "round"] | None = None


class CompanySettingsUpdate(BaseModel):
    """Hiring-behavior + privacy settings; omitted fields stay untouched,
    null resets.

    ``quiz_expired_reissue`` decides what a candidate's expired-link
    request does (27c): 'manual' (default) records it for the team,
    'auto' re-issues a fresh link once without waiting for a recruiter.

    The privacy keys feed the candidate-facing privacy notice and the
    retention engine: ``legal_name`` is the controller identity shown to
    candidates (unset → display name), ``privacy_contact_email`` receives
    rights requests, ``retention_months`` is the post-decision retention
    window (unset → platform default), ``privacy_policy_url`` lets a company
    link its own policy instead of the generated notice.
    """

    quiz_expired_reissue: Literal["manual", "auto"] | None = None
    legal_name: str | None = Field(default=None, min_length=1, max_length=200)
    privacy_contact_email: EmailStr | None = None
    retention_months: int | None = Field(default=None, ge=1, le=24)
    privacy_policy_url: HttpUrl | None = None
