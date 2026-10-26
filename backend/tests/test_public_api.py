from uuid import uuid4

import pytest
from httpx import AsyncClient

from app.core.config import settings
from tests.db import database_reachable

pytestmark = pytest.mark.skipif(
    not database_reachable(), reason="database not reachable (start postgres or use CI)"
)

FORBIDDEN_PUBLIC_FIELDS = {"id", "status", "quiz_config", "company_id", "created_at", "updated_at"}


@pytest.fixture
def multi_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "mode", "multi")


async def _register(client: AsyncClient) -> str:
    """Register a company; returns its public slug (from the public page)."""
    company_name = f"Public Co {uuid4().hex[:6]}"
    resp = await client.post(
        "/api/v1/auth/register",
        json={
            "company_name": company_name,
            "email": f"admin-{uuid4().hex[:8]}@ganek-ci.dev",
            "password": "a-long-secure-password",
        },
    )
    assert resp.status_code == 201, resp.text
    return company_name.lower().replace(" ", "-")


async def _create_and_publish(client: AsyncClient, title: str, **overrides: object) -> dict:
    payload: dict[str, object] = {"title": title, "tags": ["python"], **overrides}
    job = (await client.post("/api/v1/jobs", json=payload)).json()
    resp = await client.post(f"/api/v1/jobs/{job['id']}/publish")
    assert resp.status_code == 200
    return resp.json()


@pytest.mark.usefixtures("migrated_db", "multi_mode")
async def test_public_company_page_lists_only_published(client: AsyncClient) -> None:
    slug = await _register(client)
    published = await _create_and_publish(client, "Published Role")
    draft = (await client.post("/api/v1/jobs", json={"title": "Draft Role"})).json()
    closed = await _create_and_publish(client, "Closed Role")
    await client.post(f"/api/v1/jobs/{closed['id']}/close")

    # public page requires no auth
    await client.post("/api/v1/auth/logout")
    resp = await client.get(f"/api/v1/public/companies/{slug}")
    assert resp.status_code == 200, resp.text
    page = resp.json()
    assert page["company"]["slug"] == slug
    assert [j["slug"] for j in page["jobs"]] == [published["slug"]]
    assert draft["slug"] not in [j["slug"] for j in page["jobs"]]


@pytest.mark.usefixtures("migrated_db", "multi_mode")
async def test_public_schemas_leak_no_internal_fields(client: AsyncClient) -> None:
    slug = await _register(client)
    job = await _create_and_publish(client, "Leak Check Role")
    await client.post("/api/v1/auth/logout")

    page = (await client.get(f"/api/v1/public/companies/{slug}")).json()
    assert not FORBIDDEN_PUBLIC_FIELDS & set(page["jobs"][0])
    assert not {"id", "created_at", "updated_at", "settings"} & set(page["company"])

    detail = (await client.get(f"/api/v1/public/companies/{slug}/jobs/{job['slug']}")).json()
    assert not FORBIDDEN_PUBLIC_FIELDS & set(detail)
    assert detail["title"] == "Leak Check Role"


@pytest.mark.usefixtures("migrated_db", "multi_mode")
async def test_public_job_detail_404s(client: AsyncClient) -> None:
    slug = await _register(client)
    draft = (await client.post("/api/v1/jobs", json={"title": "Hidden Draft"})).json()
    await client.post("/api/v1/auth/logout")

    assert (await client.get("/api/v1/public/companies/no-such-co")).status_code == 404
    assert (
        await client.get(f"/api/v1/public/companies/{slug}/jobs/{draft['slug']}")
    ).status_code == 404
    assert (await client.get(f"/api/v1/public/companies/{slug}/jobs/nope")).status_code == 404


@pytest.mark.usefixtures("migrated_db")
async def test_single_mode_company_endpoint(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "mode", "multi")
    await _register(client)
    job = await _create_and_publish(client, "Single Mode Role")
    await client.post("/api/v1/auth/logout")

    monkeypatch.setattr(settings, "mode", "single")
    resp = await client.get("/api/v1/public/company")
    assert resp.status_code == 200
    # the oldest company on the instance answers; it exists and serves jobs
    assert "company" in resp.json()

    # multi mode refuses the single-mode route
    monkeypatch.setattr(settings, "mode", "multi")
    assert (await client.get("/api/v1/public/company")).status_code == 404
    assert job["slug"]  # published fixture used


@pytest.mark.usefixtures("migrated_db", "multi_mode")
async def test_public_payloads_carry_salary_period_and_closes_at(client: AsyncClient) -> None:
    slug = await _register(client)
    job = await _create_and_publish(
        client, "Deadline Role", salary_period="month", closes_at="2026-12-01"
    )
    await client.post("/api/v1/auth/logout")

    page = (await client.get(f"/api/v1/public/companies/{slug}")).json()
    assert page["jobs"][0]["salary_period"] == "month"

    detail = (await client.get(f"/api/v1/public/companies/{slug}/jobs/{job['slug']}")).json()
    assert detail["salary_period"] == "month"
    assert detail["closes_at"].startswith("2026-12-01T00:00:00")


async def _draft(client: AsyncClient, title: str) -> dict:
    resp = await client.post("/api/v1/jobs", json={"title": title})
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _preview_token(client: AsyncClient, job_id: str) -> str:
    resp = await client.post(f"/api/v1/jobs/{job_id}/preview-link")
    assert resp.status_code == 200, resp.text
    link = resp.json()
    assert "preview=" in link["url"] and link["expires_at"]
    return link["url"].split("preview=")[1]


@pytest.mark.usefixtures("migrated_db", "multi_mode")
async def test_preview_link_shows_a_draft_and_only_that_draft(client: AsyncClient) -> None:
    slug = await _register(client)
    draft = await _draft(client, "Hidden Draft")
    other = await _draft(client, "Other Draft")
    link = (await client.post(f"/api/v1/jobs/{draft['id']}/preview-link")).json()
    assert f"/jobs/{draft['slug']}?preview=" in link["url"]
    token = link["url"].split("preview=")[1]

    base = f"/api/v1/public/companies/{slug}/jobs"
    shown = await client.get(f"{base}/{draft['slug']}", params={"preview": token})
    assert shown.status_code == 200, shown.text
    assert shown.json()["title"] == "Hidden Draft"
    assert (
        await client.get(f"{base}/{other['slug']}", params={"preview": token})
    ).status_code == 404
    assert (
        await client.get(f"{base}/{draft['slug']}", params={"preview": "garbage"})
    ).status_code == 404
    assert (await client.get(f"{base}/{draft['slug']}")).status_code == 404


@pytest.mark.usefixtures("migrated_db", "multi_mode")
async def test_preview_token_is_ignored_on_a_published_job(client: AsyncClient) -> None:
    slug = await _register(client)
    job = await _create_and_publish(client, "Live Role")
    token = await _preview_token(client, job["id"])
    url = f"/api/v1/public/companies/{slug}/jobs/{job['slug']}"
    plain = await client.get(url)
    with_token = await client.get(url, params={"preview": token})
    with_junk = await client.get(url, params={"preview": "junk"})
    assert plain.status_code == with_token.status_code == with_junk.status_code == 200
    assert plain.json() == with_token.json() == with_junk.json()


@pytest.mark.usefixtures("migrated_db", "multi_mode")
async def test_preview_token_never_lets_a_draft_take_applications(client: AsyncClient) -> None:
    slug = await _register(client)
    draft = await _draft(client, "Hidden Draft")
    token = await _preview_token(client, draft["id"])
    base = f"/api/v1/public/companies/{slug}/jobs/{draft['slug']}"
    assert (
        await client.post(f"{base}/apply/upload-url", params={"preview": token})
    ).status_code == 404
    resp = await client.post(
        f"{base}/apply",
        params={"preview": token},
        json={"name": "Nope", "email": "nope@ganek-ci.dev"},
    )
    assert resp.status_code == 404


@pytest.mark.usefixtures("migrated_db", "multi_mode")
async def test_preview_token_from_another_company_404s(client: AsyncClient) -> None:
    await _register(client)
    draft = await _draft(client, "Hidden Draft")
    token = await _preview_token(client, draft["id"])
    await client.post("/api/v1/auth/logout")
    other_slug = await _register(client)
    resp = await client.get(
        f"/api/v1/public/companies/{other_slug}/jobs/{draft['slug']}", params={"preview": token}
    )
    assert resp.status_code == 404
