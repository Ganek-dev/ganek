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
- the base never carries a trailing slash, whatever the operator typed;
- a company serving a verified custom domain (multi mode, plan still
  includes custom domains) gets its careers tree - landing, jobs, one job,
  privacy notice - on ``https://<domain>`` at the root, the same rule the
  frontend middleware's Host rewrite serves; everything else (token pages,
  admin, API, logo) stays on the instance origin;
- without one, a multi-mode instance with ``tenant_domain`` set serves the
  careers tree on the tenant subdomain ``https://<slug>.<tenant_domain>``
  (decision 2026-10-24), unless the slug is reserved or not a DNS label.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING
from urllib.parse import urlsplit

from app.core import plans
from app.core.config import settings
from app.services.slugs import is_reserved_company_slug

if TYPE_CHECKING:
    from app.models import Company

API_PREFIX = "/api/v1"

_DNS_LABEL = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")


def _base(company: Company | None = None) -> str:
    """Origin the public frontend is reachable on.

    ``company`` is unused today; it is the hook for per-tenant domains.
    """
    del company
    return settings.public_base_url.rstrip("/")


def instance_host() -> str:
    """The bare host the instance answers on (no scheme, port or trailing
    dot), lowercase; empty when the base URL carries none. Custom domains
    refuse names under it."""
    return (urlsplit(_base()).hostname or "").lower().rstrip(".")


def custom_careers_domain(company: Company) -> str | None:
    """The verified custom domain the company's careers tree is served on,
    or None. Mirrors ``services.custom_domains.company_for_host`` (verified
    and the plan still includes custom domains) plus the resolve endpoint's
    multi-mode-only rule, so a link never points at a host that would not
    route: a pending claim or a downgraded plan falls back to the slug URL."""
    if settings.mode != "multi":
        return None
    if not company.custom_domain or company.custom_domain_verified_at is None:
        return None
    if not plans.get_plan_policy().custom_domains(company):
        return None
    return company.custom_domain


def tenant_domain() -> str | None:
    """The parent domain of the tenant careers subdomains (``ganek.io``),
    lowercase without a scheme, port or trailing dot; None in single mode
    or when unset."""
    if settings.mode != "multi" or not settings.tenant_domain:
        return None
    raw = settings.tenant_domain.strip().lower()
    host = (urlsplit(raw).hostname if "//" in raw else raw.partition(":")[0]) or ""
    return host.rstrip(".") or None


def tenant_subdomain_label_ok(label: str) -> bool:
    """A company slug may be a tenant subdomain when it is one valid DNS
    label and not a platform name (``app``, ``api``, brand words...)."""
    return bool(_DNS_LABEL.match(label)) and not is_reserved_company_slug(label)


def tenant_subdomain(company: Company) -> str | None:
    """``<slug>.<tenant_domain>`` when subdomains are on and the slug can be
    one; None otherwise (the slug URL stays)."""
    parent = tenant_domain()
    if parent is None or not tenant_subdomain_label_ok(company.slug):
        return None
    return f"{company.slug}.{parent}"


def careers_host(company: Company) -> str | None:
    """The host the company's careers tree is served on at its root: the
    verified custom domain, else the tenant subdomain, else None (served
    under ``/c/{slug}`` on the instance origin, or at the root in single
    mode). Admin share links, the canonical 301 and every careers link use
    this one rule."""
    return custom_careers_domain(company) or tenant_subdomain(company)


def careers_url(company: Company) -> str:
    """Careers landing page: the root in single mode, ``/c/{slug}`` in multi,
    the root of the verified custom domain or the tenant subdomain when the
    company has one."""
    domain = careers_host(company)
    if domain is not None:
        return f"https://{domain}"
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


def admin_billing_url(company: Company) -> str:
    """Billing settings page (hosted only, card B1c): the 402 upgrade link
    and the Stripe Checkout and portal return address."""
    return f"{_base(company)}/admin/billing"


def admin_applicant_url(company: Company, application_id: object) -> str:
    """The applicant open in the admin list (interviewer mails and invites)."""
    return f"{_base(company)}/admin/applicants?selected={application_id}"


def application_cv_api_url(company: Company, application_id: object) -> str:
    """API-key download of an applicant's CV (the webhook payload's ``cv.url``)."""
    return f"{_base(company)}{API_PREFIX}/applications/{application_id}/cv"


def scorecard_url(company: Company, application_id: object, *, reviewer: bool) -> str:
    """Where a scorecard request lands: staff open the applicant with the
    scorecard card focused, a reviewer-role user gets the slim review page."""
    if reviewer:
        return f"{_base(company)}/review/{application_id}"
    return f"{admin_applicant_url(company, application_id)}&scorecard=1"


def invite_url(company: Company, invite_token: str) -> str:
    return f"{_base(company)}/invite/{invite_token}"


def email_verify_url(company: Company, token: str) -> str:
    return f"{_base(company)}/verify?token={token}"


def password_reset_url(company: Company, token: str) -> str:
    return f"{_base(company)}/reset?token={token}"


def logo_url(company: Company, digest: str) -> str:
    """Absolute, immutable logo URL (Google Jobs JSON-LD needs an absolute
    one): the content digest is in the path, so a replaced logo gets a new
    URL and the old one can be cached for a year by any CDN or proxy."""
    return f"{_base(company)}{API_PREFIX}/public/companies/{company.slug}/logo/{digest}"


def google_oauth_redirect_uri() -> str:
    """Google sign-in callback; the override serves split admin/public origins."""
    if settings.google_redirect_url:
        return settings.google_redirect_url
    return f"{_base()}{API_PREFIX}/auth/google/callback"
