from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, HttpUrl, field_validator

from app.core.config import settings as app_settings
from app.schemas.scorecards import ScorecardCriterion, validate_criteria
from app.services import email_providers
from app.services.screening import ScreeningQuestion, validate_questions


class UsageOut(BaseModel):
    """Per-tenant abuse-guard counters (GET /company/usage). A limit of 0
    means that guard is off; ``warnings`` lists counters at 80% or more."""

    emails_today: int
    emails_per_day_limit: int
    applications_this_hour: int
    applications_per_hour_limit: int
    active_jobs: int
    active_jobs_limit: int
    warnings: list[str]


class CompanySummary(BaseModel):
    """What any signed-in user may know about their company: enough to build
    the public careers and job URLs (slug + instance mode). The branding
    and settings payload stays admin-only in ``CompanyOut``."""

    model_config = ConfigDict(from_attributes=True)

    slug: str
    name: str
    mode: Literal["single", "multi"] = Field(default_factory=lambda: app_settings.mode)
    # the default screening questions new jobs start with: members create and
    # edit jobs, so the editor's prefill and "Reset to company defaults" need
    # the set; preferred answers are recruiter-internal, never candidate-facing
    screening_questions: list[ScreeningQuestion] = []
    # the default scorecard criteria new jobs start with (members edit job templates)
    scorecard_template: list[ScorecardCriterion] = []


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
    screening_questions: list[ScreeningQuestion] = []
    scorecard_template: list[ScorecardCriterion] = []
    # not a column - the instance's deployment mode, so admin surfaces can
    # render the real careers URL (single mode serves it at the root)
    mode: Literal["single", "multi"] = Field(default_factory=lambda: app_settings.mode)
    # not a column - whether outbound email can be delivered at all (any
    # provider, the key name predates GANEK_EMAIL_PROVIDER); the admin
    # banner ("candidates are NOT receiving email") keys off this
    smtp_configured: bool = Field(default_factory=email_providers.configured)


class BrandingUpdate(BaseModel):
    """Branding-only patch; omitted fields stay untouched, null resets.

    Logo upload arrives with its own storage flow in a follow-up - the
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
    candidates (unset -> display name), ``privacy_contact_email`` receives
    rights requests, ``retention_months`` is the post-decision retention
    window (unset -> platform default), ``privacy_policy_url`` lets a company
    link its own policy instead of the generated notice.
    """

    quiz_expired_reissue: Literal["manual", "auto"] | None = None
    legal_name: str | None = Field(default=None, min_length=1, max_length=200)
    privacy_contact_email: EmailStr | None = None
    retention_months: int | None = Field(default=None, ge=1, le=24)
    privacy_policy_url: HttpUrl | None = None
    stage_limit_days: int | None = Field(default=None, ge=1, le=60)
    # a column, not a settings key (0039): the list replaces the company set;
    # omitted = untouched. Validated like the job's list (ids filled, <= 20).
    screening_questions: list[ScreeningQuestion] | None = None

    @field_validator("screening_questions", mode="before")
    @classmethod
    def _validate_questions(cls, value: object) -> object:
        if isinstance(value, list):
            raw: list[dict[str, Any]] = [
                item.model_dump() if isinstance(item, ScreeningQuestion) else item for item in value
            ]
            return validate_questions(raw)
        return value

    # a column (0042): the list replaces the company default; omitted = untouched
    scorecard_template: list[ScorecardCriterion] | None = None

    @field_validator("scorecard_template")
    @classmethod
    def _validate_template(cls, value: list[ScorecardCriterion] | None) -> object:
        return validate_criteria(value)
