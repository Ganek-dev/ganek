"""``app.core.urls`` is the only owner of the public base URL.

Table-driven over both modes so a per-tenant-domain change later has one
test to extend, plus a source guard that keeps inline ``public_base_url``
f-strings from creeping back (#144 was exactly that).
"""

from __future__ import annotations

import pathlib
import re
from collections.abc import Callable
from datetime import UTC, datetime

import pytest

from app.core import plans, urls
from app.core.config import settings
from app.core.plans import SelfHostedPolicy
from app.models import Company

APP_DIR = pathlib.Path(urls.__file__).resolve().parents[1]


def _company() -> Company:
    return Company(slug="acme", name="Acme Labs", settings={})


Builder = Callable[[Company], str]

CASES: list[tuple[str, Builder, str, str]] = [
    # name, builder, expected in single mode, expected in multi mode
    ("careers", urls.careers_url, "", "/c/acme"),
    ("jobs", urls.jobs_url, "/jobs", "/c/acme/jobs"),
    (
        "job",
        lambda c: urls.job_url(c, "backend-dev"),
        "/jobs/backend-dev",
        "/c/acme/jobs/backend-dev",
    ),
    ("privacy", urls.privacy_notice_url, "/privacy", "/c/acme/privacy"),
    ("quiz", lambda c: urls.quiz_url(c, "tok"), "/quiz/tok", "/quiz/tok"),
    ("status", lambda c: urls.status_url(c, "tok"), "/application/tok", "/application/tok"),
    ("interview", lambda c: urls.interview_url(c, "tok"), "/interview/tok", "/interview/tok"),
    ("invite", lambda c: urls.invite_url(c, "tok"), "/invite/tok", "/invite/tok"),
    ("verify", lambda c: urls.email_verify_url(c, "tok"), "/verify?token=tok", "/verify?token=tok"),
    ("reset", lambda c: urls.password_reset_url(c, "tok"), "/reset?token=tok", "/reset?token=tok"),
    (
        "applicant",
        lambda c: urls.admin_applicant_url(c, "app-1"),
        "/admin/applicants?selected=app-1",
        "/admin/applicants?selected=app-1",
    ),
    (
        "logo",
        lambda c: urls.logo_url(c, "0123456789abcdef"),
        "/api/v1/public/companies/acme/logo/0123456789abcdef",
        "/api/v1/public/companies/acme/logo/0123456789abcdef",
    ),
    (
        "cv_api",
        lambda c: urls.application_cv_api_url(c, "app-1"),
        "/api/v1/applications/app-1/cv",
        "/api/v1/applications/app-1/cv",
    ),
]


@pytest.mark.parametrize("mode", ["single", "multi"])
@pytest.mark.parametrize(("name", "build", "single", "multi"), CASES, ids=[c[0] for c in CASES])
def test_builders_are_mode_aware_and_strip_the_trailing_slash(
    monkeypatch: pytest.MonkeyPatch, mode: str, name: str, build: Builder, single: str, multi: str
) -> None:
    monkeypatch.setattr(settings, "public_base_url", "https://jobs.example.com/")
    monkeypatch.setattr(settings, "mode", mode)
    expected = single if mode == "single" else multi
    assert build(_company()) == f"https://jobs.example.com{expected}"


def test_google_redirect_uri_prefers_the_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "public_base_url", "https://jobs.example.com/")
    monkeypatch.setattr(settings, "google_redirect_url", None)
    assert (
        urls.google_oauth_redirect_uri() == "https://jobs.example.com/api/v1/auth/google/callback"
    )
    monkeypatch.setattr(settings, "google_redirect_url", "https://admin.example.com/cb")
    assert urls.google_oauth_redirect_uri() == "https://admin.example.com/cb"


def test_public_base_url_is_read_only_by_urls_and_settings() -> None:
    """Acceptance line of the card: nothing outside urls.py builds public links."""
    pattern = re.compile(r"\bpublic_base_url\b")
    offenders = sorted(
        str(path.relative_to(APP_DIR))
        for path in APP_DIR.rglob("*.py")
        if path.name not in {"urls.py", "config.py"}
        and any(pattern.search(line) for line in path.read_text().splitlines())
    )
    assert offenders == []


# --- verified custom domain (board card "Custom domains", slice 6) ----------


class _DomainsPolicy(SelfHostedPolicy):
    name = "test_team"

    def custom_domains(self, company: Company) -> bool:
        return True


def _domain_company(*, verified: bool = True) -> Company:
    company = _company()
    company.custom_domain = "careers.acme.com"
    company.custom_domain_verified_at = datetime(2026, 11, 8, tzinfo=UTC) if verified else None
    return company


@pytest.fixture
def team_multi(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "public_base_url", "https://jobs.example.com/")
    monkeypatch.setattr(settings, "mode", "multi")
    monkeypatch.setattr(plans, "get_plan_policy", lambda: _DomainsPolicy())


CAREERS_TREE: list[tuple[str, Builder, str]] = [
    ("careers", urls.careers_url, ""),
    ("jobs", urls.jobs_url, "/jobs"),
    ("job", lambda c: urls.job_url(c, "backend-dev"), "/jobs/backend-dev"),
    ("privacy", urls.privacy_notice_url, "/privacy"),
]


@pytest.mark.usefixtures("team_multi")
@pytest.mark.parametrize(("name", "build", "path"), CAREERS_TREE, ids=[c[0] for c in CAREERS_TREE])
def test_careers_tree_moves_to_the_verified_domain_root(
    name: str, build: Builder, path: str
) -> None:
    assert build(_domain_company()) == f"https://careers.acme.com{path}"


@pytest.mark.usefixtures("team_multi")
@pytest.mark.parametrize(
    ("name", "build", "single", "multi"),
    [c for c in CASES if c[0] not in {"careers", "jobs", "job", "privacy"}],
    ids=[c[0] for c in CASES if c[0] not in {"careers", "jobs", "job", "privacy"}],
)
def test_token_admin_api_and_logo_links_stay_on_the_instance(
    name: str, build: Builder, single: str, multi: str
) -> None:
    assert build(_domain_company()) == f"https://jobs.example.com{multi}"


@pytest.mark.usefixtures("team_multi")
def test_pending_domain_keeps_the_slug_url() -> None:
    company = _domain_company(verified=False)
    assert urls.custom_careers_domain(company) is None
    assert urls.careers_url(company) == "https://jobs.example.com/c/acme"


def test_plan_without_custom_domains_keeps_the_slug_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "public_base_url", "https://jobs.example.com")
    monkeypatch.setattr(settings, "mode", "multi")
    monkeypatch.setattr(plans, "get_plan_policy", lambda: SelfHostedPolicy())
    assert urls.job_url(_domain_company(), "x") == "https://jobs.example.com/c/acme/jobs/x"


@pytest.mark.usefixtures("team_multi")
def test_single_mode_never_uses_a_custom_domain(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "mode", "single")
    assert urls.careers_url(_domain_company()) == "https://jobs.example.com"
