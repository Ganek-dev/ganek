"""Single owner of every absolute public URL the backend hands out.

Every link that reaches a candidate, a recruiter's inbox or a third party
(emails, the jobs feed, the logo, OAuth) is built here. Nothing else may
read ``settings.public_base_url`` (test-enforced): when per-tenant custom
domains land, ``_base`` is the one place that learns to pick the tenant's
host, and every builder below already takes the company it is for.

Rules kept here so they cannot drift again (see #144):

- single mode serves the careers site at the root, multi mode under
  ``/c/{slug}``; candidate pages, the feed and the privacy notice follow
  that prefix, while capability-token pages (quiz, status, interview,
  invite, verify, reset) are mode-independent;
- the base never carries a trailing slash, whatever the operator typed.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.core.config import settings

if TYPE_CHECKING:
    from app.models import Company

API_PREFIX = "/api/v1"


def _base(company: Company | None = None) -> str:
    """Origin the public frontend is reachable on.

    ``company`` is unused today; it is the hook for per-tenant domains.
    """
    del company
    return settings.public_base_url.rstrip("/")


def careers_url(company: Company) -> str:
    """Careers landing page: the root in single mode, ``/c/{slug}`` in multi."""
    base = _base(company)
    return base if settings.mode == "single" else f"{base}/c/{company.slug}"


def jobs_url(company: Company) -> str:
    """Published-roles listing under the careers page."""
    return f"{careers_url(company)}/jobs"


def job_url(company: Company, job_slug: str) -> str:
    """One role's page (the feed's ``apply_url``)."""
    return f"{jobs_url(company)}/{job_slug}"


def privacy_notice_url(company: Company) -> str:
    """Candidate privacy notice (mode-aware, linked from every candidate email)."""
    return f"{careers_url(company)}/privacy"


def quiz_url(company: Company, quiz_token: str) -> str:
    return f"{_base(company)}/quiz/{quiz_token}"


def status_url(company: Company, status_token: str) -> str:
    return f"{_base(company)}/application/{status_token}"


def interview_url(company: Company, interview_token: str) -> str:
    return f"{_base(company)}/interview/{interview_token}"


def invite_url(company: Company, invite_token: str) -> str:
    return f"{_base(company)}/invite/{invite_token}"


def email_verify_url(company: Company, token: str) -> str:
    return f"{_base(company)}/verify?token={token}"


def password_reset_url(company: Company, token: str) -> str:
    return f"{_base(company)}/reset?token={token}"


def logo_url(company: Company, version: int) -> str:
    """Absolute logo URL (Google Jobs JSON-LD needs one); ``version`` cache-busts."""
    return f"{_base(company)}{API_PREFIX}/public/companies/{company.slug}/logo?v={version}"


def google_oauth_redirect_uri() -> str:
    """Google sign-in callback; the override serves split admin/public origins."""
    if settings.google_redirect_url:
        return settings.google_redirect_url
    return f"{_base()}{API_PREFIX}/auth/google/callback"
