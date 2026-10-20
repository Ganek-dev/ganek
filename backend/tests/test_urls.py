"""``app.core.urls`` is the only owner of the public base URL.

Table-driven over both modes so a per-tenant-domain change later has one
test to extend, plus a source guard that keeps inline ``public_base_url``
f-strings from creeping back (#144 was exactly that).
"""

from __future__ import annotations

import pathlib
import re
from collections.abc import Callable

import pytest

from app.core import urls
from app.core.config import settings
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
        "logo",
        lambda c: urls.logo_url(c, 42),
        "/api/v1/public/companies/acme/logo?v=42",
        "/api/v1/public/companies/acme/logo?v=42",
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
