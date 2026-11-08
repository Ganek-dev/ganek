"""Custom careers domains, slice 4 (board card "Custom domains + subdomain
routing"): Host header -> company for the frontend middleware, and the
Caddy on-demand TLS ``ask`` check. Only a verified domain on a plan that
includes custom domains ever resolves; tenant A's Host never reaches tenant
B. The core suite runs without ee/, so stand-in policies play the plans."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import update

from app.core import plans
from app.core.config import settings
from app.core.plans import SelfHostedPolicy
from app.models import Company
from app.services import custom_domains
from app.services.custom_domains import normalize_host
from tests.db import database_reachable


class _DomainsPolicy(SelfHostedPolicy):
    name = "test_team"

    def custom_domains(self, company: Company) -> bool:
        return True


# --- host normalization (no database) ---------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("careers.acme.com", "careers.acme.com"),
        ("Careers.ACME.com", "careers.acme.com"),
        ("careers.acme.com.", "careers.acme.com"),
        ("careers.acme.com:443", "careers.acme.com"),
        (" careers.acme.com:8080 ", "careers.acme.com"),
    ],
)
def test_normalize_host_accepts_names_with_ports(raw: str, expected: str) -> None:
    assert normalize_host(raw) == expected


@pytest.mark.parametrize(
    "raw",
    ["", "localhost", "10.0.0.1", "10.0.0.1:80", "[::1]:443", "acme.com:https", "a b.com", "x..y"],
)
def test_normalize_host_refuses_non_names(raw: str) -> None:
    assert normalize_host(raw) is None


# --- API -------------------------------------------------------------------

db_only = pytest.mark.skipif(
    not database_reachable(), reason="database not reachable (start postgres or use CI)"
)


@pytest.fixture
def multi(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "mode", "multi")


@pytest.fixture
def team(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(plans, "get_plan_policy", lambda: _DomainsPolicy())


@pytest.fixture
def dns(monkeypatch: pytest.MonkeyPatch) -> dict[str, list[str]]:
    records: dict[str, list[str]] = {}

    async def fake_lookup(name: str) -> list[str]:
        return records.get(name, [])

    monkeypatch.setattr(custom_domains, "lookup_txt", fake_lookup)
    return records


def _domain() -> str:
    return f"careers-{uuid4().hex[:8]}.acme-ci.com"


async def _tenant(
    client: AsyncClient, dns: dict[str, list[str]], *, verify: bool = True
) -> tuple[str, str]:
    """Register a workspace, claim a fresh domain and (by default) verify it.
    Returns (slug, domain)."""
    client.cookies.clear()
    resp = await client.post(
        "/api/v1/auth/register",
        json={
            "company_name": f"Route Co {uuid4().hex[:6]}",
            "email": f"admin-{uuid4().hex[:8]}@ganek-ci.dev",
            "password": "a-long-secure-password",
        },
    )
    assert resp.status_code == 201, resp.text
    slug = (await client.get("/api/v1/company")).json()["slug"]
    domain = _domain()
    claimed = (await client.put("/api/v1/company/domain", json={"domain": domain})).json()
    if verify:
        dns[claimed["txt_name"]] = [claimed["txt_value"]]
        resp = await client.post("/api/v1/company/domain/verify")
        assert resp.json()["status"] == "verified", resp.text
    return slug, domain


async def _resolve(client: AsyncClient, host: str) -> tuple[int, dict[str, str]]:
    resp = await client.get("/api/v1/public/domains/resolve", params={"host": host})
    return resp.status_code, resp.json()


async def _ask(client: AsyncClient, domain: str) -> int:
    resp = await client.get("/api/v1/public/domains/tls-ask", params={"domain": domain})
    return resp.status_code


@db_only
@pytest.mark.usefixtures("migrated_db", "multi", "team")
async def test_host_never_crosses_tenants(client: AsyncClient, dns: dict[str, list[str]]) -> None:
    slug_a, domain_a = await _tenant(client, dns)
    slug_b, domain_b = await _tenant(client, dns)
    client.cookies.clear()

    assert await _resolve(client, domain_a) == (200, {"slug": slug_a, "domain": domain_a})
    assert await _resolve(client, domain_b) == (200, {"slug": slug_b, "domain": domain_b})
    # case, port and trailing dot are the same host
    code, body = await _resolve(client, f"{domain_a.upper()}.:443")
    assert (code, body["slug"]) == (200, slug_a)
    # neighbours of a verified name are not that name
    for near in (f"www.{domain_a}", domain_a.replace("careers-", "careers-x"), "acme-ci.com"):
        assert (await _resolve(client, near))[0] == 404
        assert await _ask(client, near) == 404

    assert await _ask(client, domain_a) == 200
    assert await _ask(client, domain_b) == 200


@db_only
@pytest.mark.usefixtures("migrated_db", "multi", "team")
async def test_pending_domain_never_routes_or_gets_a_certificate(
    client: AsyncClient, dns: dict[str, list[str]]
) -> None:
    _slug, domain = await _tenant(client, dns, verify=False)
    client.cookies.clear()
    assert (await _resolve(client, domain))[0] == 404
    assert await _ask(client, domain) == 404


@db_only
@pytest.mark.usefixtures("migrated_db", "multi", "team")
async def test_removed_domain_stops_routing(client: AsyncClient, dns: dict[str, list[str]]) -> None:
    _slug, domain = await _tenant(client, dns)
    assert (await _resolve(client, domain))[0] == 200
    assert (await client.delete("/api/v1/company/domain")).status_code == 200
    assert (await _resolve(client, domain))[0] == 404
    assert await _ask(client, domain) == 404


@db_only
@pytest.mark.usefixtures("migrated_db", "multi", "team")
async def test_downgraded_plan_stops_routing(
    client: AsyncClient, dns: dict[str, list[str]], monkeypatch: pytest.MonkeyPatch
) -> None:
    _slug, domain = await _tenant(client, dns)
    monkeypatch.setattr(plans, "get_plan_policy", lambda: SelfHostedPolicy())
    assert (await _resolve(client, domain))[0] == 404
    assert await _ask(client, domain) == 404


@db_only
@pytest.mark.usefixtures("migrated_db", "multi", "team")
async def test_suspended_tenant_keeps_resolving(
    client: AsyncClient, dns: dict[str, list[str]], db_session
) -> None:
    slug, domain = await _tenant(client, dns)
    await db_session.execute(
        update(Company).where(Company.slug == slug).values(suspended_at=datetime.now(UTC))
    )
    await db_session.commit()
    # the domain still resolves and keeps its certificate; the careers page
    # it is rewritten to answers the unavailable notice
    assert (await _resolve(client, domain))[0] == 200
    assert await _ask(client, domain) == 200
    assert (await client.get(f"/api/v1/public/companies/{slug}")).status_code == 503


@db_only
@pytest.mark.usefixtures("migrated_db", "team")
async def test_single_mode_never_resolves(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "mode", "single")
    assert (await _resolve(client, "careers.acme-ci.com"))[0] == 404
    assert await _ask(client, "careers.acme-ci.com") == 404
