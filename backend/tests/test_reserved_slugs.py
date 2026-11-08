"""Reserved company slugs (card "Custom domains + subdomain routing", the
reserved-slug slice): a hosted signup can never claim a platform host such
as app, api or status, nor the brand, before tenant subdomains go live."""

from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.security import GOOGLE_SIGNUP_COOKIE_NAME, create_google_signup_token
from app.models import Company
from app.services import auth as auth_service
from app.services.auth import RESERVED_COMPANY_NAME_DETAIL
from app.services.slugs import (
    RESERVED_COMPANY_SLUGS,
    is_reserved_company_slug,
    slugify,
)
from tests.db import database_reachable

# the list the decision of 2026-10-24 and the card name; the set may grow,
# it must never shrink below this
CARD_LIST = (
    "app",
    "api",
    "www",
    "admin",
    "login",
    "mail",
    "status",
    "docs",
    "help",
    "billing",
    "demo",
    "ganek",
)


@pytest.mark.parametrize("slug", sorted(set(CARD_LIST) | RESERVED_COMPANY_SLUGS))
def test_every_reserved_slug_is_refused(slug: str) -> None:
    assert is_reserved_company_slug(slug)


@pytest.mark.parametrize(
    "name",
    [
        "Ganek",
        "ganek.io",
        "Get Ganek",
        "GanekHQ",
        "ACME Ganek",
        "Vetd",
        "A-P-I",
        "Help!",
        " Status ",
    ],
)
def test_variants_and_brand_are_refused(name: str) -> None:
    assert is_reserved_company_slug(slugify(name))


@pytest.mark.parametrize(
    "name", ["Acme", "Apple", "Status Labs", "Help Scout", "Mailchimp", "Demo Day Studio", "Appian"]
)
def test_ordinary_names_pass(name: str) -> None:
    assert not is_reserved_company_slug(slugify(name))


def _payload(company_name: str) -> dict[str, str]:
    return {
        "company_name": company_name,
        "email": f"admin-{uuid4().hex[:8]}@ganek-ci.dev",
        "password": "a-long-secure-password",
    }


async def _companies_named(db: AsyncSession, name: str) -> int:
    return (
        await db.execute(select(func.count()).select_from(Company).where(Company.name == name))
    ).scalar_one()


db_only = pytest.mark.skipif(
    not database_reachable(), reason="database not reachable (start postgres or use CI)"
)


@db_only
@pytest.mark.usefixtures("migrated_db")
@pytest.mark.parametrize(
    ("name", "with_a_word"),
    [("Status", "Status Labs"), ("API", "API Works"), ("Ganek", None), ("Get Ganek", None)],
)
async def test_multi_mode_signup_refuses_reserved_name(
    client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    name: str,
    with_a_word: str | None,
) -> None:
    monkeypatch.setattr(settings, "mode", "multi")
    resp = await client.post("/api/v1/auth/register", json=_payload(name))
    assert resp.status_code == 422, resp.text
    assert resp.json()["detail"] == RESERVED_COMPANY_NAME_DETAIL
    assert await _companies_named(db_session, name) == 0
    if with_a_word is not None:
        # adding a word is enough for a platform name (never for the brand)
        ok = await client.post(
            "/api/v1/auth/register", json=_payload(f"{with_a_word} {uuid4().hex[:4]}")
        )
        assert ok.status_code == 201, ok.text


@db_only
@pytest.mark.usefixtures("migrated_db")
async def test_multi_mode_google_signup_refuses_reserved_name(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "mode", "multi")
    monkeypatch.setattr(settings, "google_client_id", "test-client-id")
    monkeypatch.setattr(settings, "google_client_secret", "test-client-secret")
    client.cookies.set(
        GOOGLE_SIGNUP_COOKIE_NAME,
        create_google_signup_token(f"sub-{uuid4().hex}", f"f-{uuid4().hex[:8]}@gmail.com"),
        path="/api/v1/auth/google",
    )
    resp = await client.post("/api/v1/auth/google/signup", json={"company_name": "Admin"})
    assert resp.status_code == 422, resp.text
    assert resp.json()["detail"] == RESERVED_COMPANY_NAME_DETAIL
    # the signup cookie survives, so the founder can retry with another name
    retry = await client.post(
        "/api/v1/auth/google/signup", json={"company_name": f"Admin Tools {uuid4().hex[:4]}"}
    )
    assert retry.status_code == 201, retry.text


def test_single_mode_keeps_any_name(monkeypatch: pytest.MonkeyPatch) -> None:
    """Single mode never shows the slug (careers at the root): no refusal."""
    monkeypatch.setattr(settings, "mode", "single")
    assert auth_service.check_company_name("Status") == "status"
    monkeypatch.setattr(settings, "mode", "multi")
    with pytest.raises(auth_service.ReservedCompanyNameError):
        auth_service.check_company_name("Status")
