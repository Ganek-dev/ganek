"""Public jobs feed (screen 25): third-party JSON with CORS + short cache."""

from uuid import uuid4

import pytest
from httpx import AsyncClient

from app.core.config import settings
from tests.db import database_reachable

pytestmark = pytest.mark.skipif(
    not database_reachable(), reason="database not reachable (start postgres or use CI)"
)


@pytest.fixture
def multi_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "mode", "multi")


async def _setup_company(client: AsyncClient) -> str:
    name = f"Feed Co {uuid4().hex[:6]}"
    resp = await client.post(
        "/api/v1/auth/register",
        json={
            "company_name": name,
            "email": f"admin-{uuid4().hex[:8]}@vetd-ci.dev",
            "password": "a-long-secure-password",
        },
    )
    assert resp.status_code == 201, resp.text
    slug = name.lower().replace(" ", "-")
    published = (
        await client.post(
            "/api/v1/jobs",
            json={"title": "Frontend Engineer", "location": "Remote", "tags": ["react"]},
        )
    ).json()
    assert (await client.post(f"/api/v1/jobs/{published['id']}/publish")).status_code == 200
    draft = (await client.post("/api/v1/jobs", json={"title": "Secret Draft Role"})).json()
    assert draft["status"] == "draft"
    await client.patch("/api/v1/company/branding", json={"primary_color": "#7E14FF"})
    await client.post("/api/v1/auth/logout")
    return slug


@pytest.mark.usefixtures("migrated_db", "multi_mode")
async def test_feed_lists_published_jobs_with_cors_and_cache(client: AsyncClient) -> None:
    slug = await _setup_company(client)
    resp = await client.get(f"/api/v1/public/companies/{slug}/jobs-feed")
    assert resp.status_code == 200, resp.text
    assert resp.headers["access-control-allow-origin"] == "*"
    assert resp.headers["cache-control"] == "public, max-age=60"

    feed = resp.json()
    assert feed["company"].startswith("Feed Co ")
    assert feed["brand_primary"] == "#7E14FF"
    assert [job["title"] for job in feed["jobs"]] == ["Frontend Engineer"]
    job = feed["jobs"][0]
    assert job["tags"] == ["react"]
    assert job["apply_url"].endswith(f"/c/{slug}/jobs/{job['slug']}")
    assert job["posted_at"] is not None
    # never leaks admin-only fields
    assert "quiz_config" not in job and "id" not in job


@pytest.mark.usefixtures("migrated_db", "multi_mode")
async def test_single_mode_feed_uses_root_apply_urls(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # register under multi (single closes registration), then read as single.
    # Single mode serves the instance's OLDEST company (shared test DB), so
    # assert the shape and the root-style URLs rather than specific content.
    await _setup_company(client)
    monkeypatch.setattr(settings, "mode", "single")
    resp = await client.get("/api/v1/public/company/jobs-feed")
    assert resp.status_code == 200, resp.text
    feed = resp.json()
    assert set(feed) == {"company", "brand_primary", "jobs"}
    for job in feed["jobs"]:
        assert "/jobs/" in job["apply_url"] and "/c/" not in job["apply_url"]


@pytest.mark.usefixtures("migrated_db", "multi_mode")
async def test_feed_unknown_company_is_404(client: AsyncClient) -> None:
    assert (await client.get("/api/v1/public/companies/nope/jobs-feed")).status_code == 404
