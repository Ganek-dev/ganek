"""Custom careers domains, slice 2 (board card "Custom domains + subdomain
routing"): claim a domain, prove it with a DNS TXT record, never route a
pending one. The core suite runs without ee/, so a stand-in policy that
allows custom domains plays the hosted Team plan; DNS is faked."""

from uuid import uuid4

import pytest
from httpx import AsyncClient

from app.core import plans
from app.core.config import settings
from app.core.plans import SelfHostedPolicy
from app.models import Company
from app.services import custom_domains
from app.services.custom_domains import InvalidDomain, normalize_domain
from tests.db import database_reachable

UPGRADE = "https://billing.ganek-ci.dev/upgrade"


class _DomainsPolicy(SelfHostedPolicy):
    name = "test_team"

    def custom_domains(self, company: Company) -> bool:
        return True


class _NoDomainsPolicy(SelfHostedPolicy):
    name = "test_free"

    def upgrade_url(self, company: Company) -> str | None:
        return UPGRADE


# --- normalization (no database) -------------------------------------------


@pytest.fixture
def platform(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "public_base_url", "https://app.ganek.io")


@pytest.mark.usefixtures("platform")
@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("careers.acme.com", "careers.acme.com"),
        ("  Careers.ACME.com. ", "careers.acme.com"),
        ("jobs.bücher.de", "jobs.xn--bcher-kva.de"),
        ("acme.co.uk", "acme.co.uk"),
    ],
)
def test_normalize_accepts_hostnames(raw: str, expected: str) -> None:
    assert normalize_domain(raw) == expected


@pytest.mark.usefixtures("platform")
@pytest.mark.parametrize(
    "raw",
    [
        "",
        "https://careers.acme.com",
        "careers.acme.com/jobs",
        "careers.acme.com:8443",
        "localhost",
        "careers",
        "10.0.0.1",
        "-bad.acme.com",
        "bad_label.acme.com",
        "a" * 64 + ".com",
        "ganek.io",
        "acme.ganek.io",
        "app.ganek.io",
        "evil.app.ganek.io",
        "dev.localhost",
    ],
)
def test_normalize_refuses_non_domains_and_platform_names(raw: str) -> None:
    with pytest.raises(InvalidDomain):
        normalize_domain(raw)


def test_self_hosted_policy_has_no_custom_domains() -> None:
    company = Company(slug="acme", name="Acme")
    assert SelfHostedPolicy().custom_domains(company) is False


def test_pending_domain_never_routes() -> None:
    company = Company(slug="acme", name="Acme", custom_domain="careers.acme.com")
    assert custom_domains.status(company) == "pending"
    assert custom_domains.verified_domain(company) is None


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


async def _register(client: AsyncClient, role: str = "admin") -> None:
    client.cookies.clear()
    resp = await client.post(
        "/api/v1/auth/register",
        json={
            "company_name": f"Domain Co {uuid4().hex[:6]}",
            "email": f"{role}-{uuid4().hex[:8]}@ganek-ci.dev",
            "password": "a-long-secure-password",
        },
    )
    assert resp.status_code == 201, resp.text


def _domain() -> str:
    return f"careers-{uuid4().hex[:8]}.acme-ci.com"


@db_only
@pytest.mark.usefixtures("migrated_db", "multi", "team")
async def test_claim_verify_and_remove(client: AsyncClient, dns: dict[str, list[str]]) -> None:
    await _register(client)
    empty = (await client.get("/api/v1/company/domain")).json()
    assert empty["available"] is True
    assert empty["status"] == "none"

    domain = _domain()
    resp = await client.put("/api/v1/company/domain", json={"domain": domain.upper()})
    assert resp.status_code == 200, resp.text
    claimed = resp.json()
    assert claimed["domain"] == domain
    assert claimed["status"] == "pending"
    assert claimed["txt_name"] == f"_ganek.{domain}"
    assert claimed["txt_value"].startswith("ganek-domain-verification=")

    # no record yet: a clear 409, still pending
    resp = await client.post("/api/v1/company/domain/verify")
    assert resp.status_code == 409
    assert f"_ganek.{domain}" in resp.json()["detail"]
    assert (await client.get("/api/v1/company/domain")).json()["status"] == "pending"

    # a record with another token proves nothing
    dns[claimed["txt_name"]] = ["ganek-domain-verification=someone-else"]
    assert (await client.post("/api/v1/company/domain/verify")).status_code == 409

    dns[claimed["txt_name"]].append(claimed["txt_value"])
    resp = await client.post("/api/v1/company/domain/verify")
    assert resp.status_code == 200, resp.text
    verified = resp.json()
    assert verified["status"] == "verified"
    assert verified["verified_at"] is not None
    assert verified["txt_name"] is None

    # re-sending the same domain keeps the verification
    resp = await client.put("/api/v1/company/domain", json={"domain": domain})
    assert resp.json()["status"] == "verified"

    # changing it starts over with a fresh token
    other = _domain()
    resp = await client.put("/api/v1/company/domain", json={"domain": other})
    assert resp.json()["status"] == "pending"
    assert resp.json()["txt_value"] != claimed["txt_value"]

    resp = await client.delete("/api/v1/company/domain")
    assert resp.status_code == 200
    assert resp.json()["status"] == "none"
    assert resp.json()["domain"] is None


@db_only
@pytest.mark.usefixtures("migrated_db", "multi", "team")
async def test_invalid_domain_is_422(client: AsyncClient) -> None:
    await _register(client)
    resp = await client.put("/api/v1/company/domain", json={"domain": "https://acme.com/jobs"})
    assert resp.status_code == 422
    assert "without https://" in resp.json()["detail"]


@db_only
@pytest.mark.usefixtures("migrated_db", "multi", "team")
async def test_pending_claim_never_blocks_the_real_owner(
    client: AsyncClient, dns: dict[str, list[str]]
) -> None:
    domain = _domain()
    # a squatter claims the domain first but cannot publish the record
    await _register(client)
    squat = (await client.put("/api/v1/company/domain", json={"domain": domain})).json()
    assert squat["status"] == "pending"

    # the real owner claims it too and verifies
    await _register(client)
    owner = (await client.put("/api/v1/company/domain", json={"domain": domain})).json()
    assert owner["status"] == "pending"
    assert owner["txt_value"] != squat["txt_value"]
    dns[owner["txt_name"]] = [owner["txt_value"]]
    assert (await client.post("/api/v1/company/domain/verify")).json()["status"] == "verified"

    # a third workspace that somehow holds a matching record still loses
    await _register(client)
    third = (await client.put("/api/v1/company/domain", json={"domain": domain})).json()
    dns[third["txt_name"]].append(third["txt_value"])
    resp = await client.post("/api/v1/company/domain/verify")
    assert resp.status_code == 409
    assert "another workspace" in resp.json()["detail"]


@db_only
@pytest.mark.usefixtures("migrated_db", "multi")
async def test_plan_without_custom_domains_is_402(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(plans, "get_plan_policy", lambda: _NoDomainsPolicy())
    await _register(client)
    out = (await client.get("/api/v1/company/domain")).json()
    assert out["available"] is False
    assert out["upgrade_url"] == UPGRADE
    resp = await client.put("/api/v1/company/domain", json={"domain": _domain()})
    assert resp.status_code == 402
    assert resp.json()["detail"]["code"] == "plan_feature"
    assert resp.json()["detail"]["upgrade_url"] == UPGRADE
    assert (await client.post("/api/v1/company/domain/verify")).status_code == 402
    # removing never needs the plan
    assert (await client.delete("/api/v1/company/domain")).status_code == 200


@db_only
@pytest.mark.usefixtures("migrated_db", "multi", "team")
async def test_members_cannot_manage_the_domain(client: AsyncClient) -> None:
    await _register(client)
    member_email = f"member-{uuid4().hex[:8]}@ganek-ci.dev"
    member_pw = "member-password-1234"
    resp = await client.post(
        "/api/v1/users", json={"email": member_email, "password": member_pw, "role": "member"}
    )
    assert resp.status_code == 201, resp.text
    await client.post("/api/v1/auth/logout")
    resp = await client.post(
        "/api/v1/auth/login", json={"email": member_email, "password": member_pw}
    )
    assert resp.status_code == 200
    assert (await client.get("/api/v1/company/domain")).status_code == 403
    resp = await client.put("/api/v1/company/domain", json={"domain": _domain()})
    assert resp.status_code == 403
