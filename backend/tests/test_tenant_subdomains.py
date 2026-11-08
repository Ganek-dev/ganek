"""Tenant careers subdomains (board card "Custom domains + subdomain
routing", slice 10): with ``tenant_domain`` set on a multi-mode instance,
company ``acme`` serves its careers pages on ``acme.<tenant_domain>``
(decision 2026-10-24). The Host lookup, the canonical 301 lookup, the TLS
ask, the careers links and the admin share URLs all follow one rule
(``urls.careers_host``): a verified custom domain wins, then the subdomain,
then the slug URL. Tenant A's subdomain never reaches tenant B."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from httpx import AsyncClient

from app.core import plans, urls
from app.core.config import settings
from app.core.plans import SelfHostedPolicy
from app.models import Company
from app.services import custom_domains
from tests.db import database_reachable

TENANT_DOMAIN = "tenants-ci.test"


class _DomainsPolicy(SelfHostedPolicy):
    name = "test_team"

    def custom_domains(self, company: Company) -> bool:
        return True


@pytest.fixture
def subdomains(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "mode", "multi")
    monkeypatch.setattr(settings, "tenant_domain", TENANT_DOMAIN)
    monkeypatch.setattr(settings, "public_base_url", "https://app.example-ci.test")


@pytest.fixture
def team(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(plans, "get_plan_policy", lambda: _DomainsPolicy())


# --- URL rules (no database) -------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("ganek.io", "ganek.io"),
        (" Ganek.IO. ", "ganek.io"),
        ("https://ganek.io/", "ganek.io"),
        ("ganek.io:443", "ganek.io"),
        ("", None),
    ],
)
def test_tenant_domain_is_a_bare_host(
    monkeypatch: pytest.MonkeyPatch, raw: str, expected: str | None
) -> None:
    monkeypatch.setattr(settings, "mode", "multi")
    monkeypatch.setattr(settings, "tenant_domain", raw)
    assert urls.tenant_domain() == expected


def test_single_mode_never_uses_subdomains(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "mode", "single")
    monkeypatch.setattr(settings, "tenant_domain", TENANT_DOMAIN)
    monkeypatch.setattr(settings, "public_base_url", "https://jobs.example.com")
    company = Company(slug="acme", name="Acme", settings={})
    assert urls.tenant_domain() is None
    assert urls.careers_url(company) == "https://jobs.example.com"


@pytest.mark.usefixtures("subdomains")
def test_careers_links_use_the_tenant_subdomain() -> None:
    company = Company(slug="acme", name="Acme", settings={})
    assert urls.careers_host(company) == f"acme.{TENANT_DOMAIN}"
    assert urls.careers_url(company) == f"https://acme.{TENANT_DOMAIN}"
    assert urls.job_url(company, "dev") == f"https://acme.{TENANT_DOMAIN}/jobs/dev"
    assert urls.privacy_notice_url(company) == f"https://acme.{TENANT_DOMAIN}/privacy"
    # token pages, admin and the logo stay on the instance origin
    assert urls.quiz_url(company, "tok") == "https://app.example-ci.test/quiz/tok"
    assert urls.logo_url(company, "ab").startswith("https://app.example-ci.test/api/v1/")


@pytest.mark.usefixtures("subdomains")
@pytest.mark.parametrize("slug", ["app", "ganek-hq", "a" * 64, "-x", "x-"])
def test_reserved_or_invalid_slugs_keep_the_slug_url(slug: str) -> None:
    company = Company(slug=slug, name="X", settings={})
    assert urls.tenant_subdomain(company) is None
    assert urls.careers_url(company) == f"https://app.example-ci.test/c/{slug}"


@pytest.mark.usefixtures("subdomains")
def test_a_verified_custom_domain_wins_over_the_subdomain(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    company = Company(
        slug="acme",
        name="Acme",
        settings={},
        custom_domain="careers.acme.com",
        custom_domain_verified_at=datetime.now(UTC),
    )
    monkeypatch.setattr(plans, "get_plan_policy", lambda: _DomainsPolicy())
    assert urls.careers_url(company) == "https://careers.acme.com"
    # a downgrade falls back to the subdomain, not the slug URL
    monkeypatch.setattr(plans, "get_plan_policy", lambda: SelfHostedPolicy())
    assert urls.careers_url(company) == f"https://acme.{TENANT_DOMAIN}"


@pytest.mark.usefixtures("subdomains")
def test_no_tenant_can_claim_a_name_under_the_tenant_domain() -> None:
    for raw in (TENANT_DOMAIN, f"careers.{TENANT_DOMAIN}", f"x.acme.{TENANT_DOMAIN}"):
        with pytest.raises(custom_domains.InvalidDomain):
            custom_domains.normalize_domain(raw)


# --- API -------------------------------------------------------------------

db_only = pytest.mark.skipif(
    not database_reachable(), reason="database not reachable (start postgres or use CI)"
)


async def _register(client: AsyncClient) -> str:
    client.cookies.clear()
    resp = await client.post(
        "/api/v1/auth/register",
        json={
            "company_name": f"Sub Co {uuid4().hex[:6]}",
            "email": f"admin-{uuid4().hex[:8]}@ganek-ci.dev",
            "password": "a-long-secure-password",
        },
    )
    assert resp.status_code == 201, resp.text
    slug: str = (await client.get("/api/v1/company")).json()["slug"]
    return slug


async def _resolve(client: AsyncClient, host: str) -> tuple[int, dict[str, str]]:
    resp = await client.get("/api/v1/public/domains/resolve", params={"host": host})
    return resp.status_code, resp.json()


async def _ask(client: AsyncClient, domain: str) -> int:
    resp = await client.get("/api/v1/public/domains/tls-ask", params={"domain": domain})
    return resp.status_code


@db_only
@pytest.mark.usefixtures("migrated_db", "subdomains")
async def test_subdomain_resolves_its_own_tenant_only(client: AsyncClient) -> None:
    slug_a = await _register(client)
    slug_b = await _register(client)
    client.cookies.clear()
    host_a, host_b = f"{slug_a}.{TENANT_DOMAIN}", f"{slug_b}.{TENANT_DOMAIN}"

    assert await _resolve(client, host_a) == (200, {"slug": slug_a, "domain": host_a})
    assert await _resolve(client, host_b) == (200, {"slug": slug_b, "domain": host_b})
    code, body = await _resolve(client, f"{host_a.upper()}.:443")
    assert (code, body["slug"]) == (200, slug_a)
    assert await _ask(client, host_a) == 200

    # nested names, the parent itself, reserved labels and unknown slugs
    # are nobody's
    for host in (
        f"www.{host_a}",
        f"{slug_b}.{host_a}",
        TENANT_DOMAIN,
        f"app.{TENANT_DOMAIN}",
        f"{slug_a}x.{TENANT_DOMAIN}",
        f"nope-{uuid4().hex[:6]}.{TENANT_DOMAIN}",
    ):
        assert (await _resolve(client, host))[0] == 404, host
        assert await _ask(client, host) == 404, host


@db_only
@pytest.mark.usefixtures("migrated_db", "subdomains")
async def test_slug_url_and_admin_point_at_the_subdomain(client: AsyncClient) -> None:
    slug = await _register(client)
    host = f"{slug}.{TENANT_DOMAIN}"
    assert (await client.get("/api/v1/company")).json()["careers_domain"] == host
    assert (await client.get("/api/v1/company/summary")).json()["careers_domain"] == host
    client.cookies.clear()
    resp = await client.get(f"/api/v1/public/domains/by-slug/{slug}")
    assert (resp.status_code, resp.json()) == (200, {"slug": slug, "domain": host})
    page = (await client.get(f"/api/v1/public/companies/{slug}")).json()
    assert page["company"]["careers_url"] == f"https://{host}"


@db_only
@pytest.mark.usefixtures("migrated_db", "subdomains", "team")
async def test_subdomain_points_at_the_verified_custom_domain(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    records: dict[str, list[str]] = {}

    async def fake_lookup(name: str) -> list[str]:
        return records.get(name, [])

    monkeypatch.setattr(custom_domains, "lookup_txt", fake_lookup)
    slug = await _register(client)
    domain = f"careers-{uuid4().hex[:8]}.acme-ci.com"
    claimed = (await client.put("/api/v1/company/domain", json={"domain": domain})).json()
    records[claimed["txt_name"]] = [claimed["txt_value"]]
    assert (await client.post("/api/v1/company/domain/verify")).json()["status"] == "verified"
    client.cookies.clear()

    # the subdomain still resolves, but names the custom domain as canonical
    # so the middleware 301s there
    host = f"{slug}.{TENANT_DOMAIN}"
    assert await _resolve(client, host) == (200, {"slug": slug, "domain": domain})
    assert await _resolve(client, domain) == (200, {"slug": slug, "domain": domain})
    resp = await client.get(f"/api/v1/public/domains/by-slug/{slug}")
    assert resp.json()["domain"] == domain


@db_only
@pytest.mark.usefixtures("migrated_db", "subdomains")
async def test_subdomains_off_in_single_mode_or_when_unset(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    slug = await _register(client)
    client.cookies.clear()
    host = f"{slug}.{TENANT_DOMAIN}"
    monkeypatch.setattr(settings, "tenant_domain", None)
    assert (await _resolve(client, host))[0] == 404
    assert (await client.get(f"/api/v1/public/domains/by-slug/{slug}")).status_code == 404
    monkeypatch.setattr(settings, "tenant_domain", TENANT_DOMAIN)
    monkeypatch.setattr(settings, "mode", "single")
    assert (await _resolve(client, host))[0] == 404
