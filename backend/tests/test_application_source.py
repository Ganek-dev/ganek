"""The apply request may carry a source label; it is normalised and stored,
and an odd value never blocks the application (spec job posts v2 5.4)."""

from uuid import uuid4

import pytest
from httpx import AsyncClient

from app.core.config import settings
from tests.db import database_reachable, s3_reachable
from tests.helpers import upload_pdf

pytestmark = pytest.mark.skipif(
    not (database_reachable() and s3_reachable()),
    reason="database and object storage required (start postgres+minio or use CI)",
)

PDF_BYTES = b"%PDF-1.4 source flow"


@pytest.fixture
def multi_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "mode", "multi")


async def _register_with_job(client: AsyncClient) -> tuple[str, str, dict[str, str]]:
    """Registers a company and publishes one job. Returns (slug, job_slug, creds)
    with the admin logged in."""
    creds = {
        "email": f"admin-{uuid4().hex[:8]}@ganek-ci.dev",
        "password": "a-long-secure-password",
    }
    name = f"Source Co {uuid4().hex[:6]}"
    resp = await client.post("/api/v1/auth/register", json={"company_name": name, **creds})
    assert resp.status_code == 201, resp.text
    job = (await client.post("/api/v1/jobs", json={"title": "Backend Engineer"})).json()
    assert (await client.post(f"/api/v1/jobs/{job['id']}/publish")).status_code == 200
    return name.lower().replace(" ", "-"), job["slug"], creds


async def _apply(client: AsyncClient, slug: str, job_slug: str, **extra: object) -> int:
    base = f"/api/v1/public/companies/{slug}/jobs/{job_slug}"
    ticket = (await client.post(f"{base}/apply/upload-url")).json()
    assert (await upload_pdf(ticket, PDF_BYTES)).is_success
    resp = await client.post(
        f"{base}/apply",
        json={
            "name": "Marta Vidal",
            "email": f"cand-{uuid4().hex[:8]}@ganek-ci.dev",
            "cv_object_key": ticket["object_key"],
            "cv_filename": "marta.pdf",
            **extra,
        },
    )
    return resp.status_code


async def _sources_seen(client: AsyncClient, creds: dict[str, str]) -> list[str | None]:
    assert (await client.post("/api/v1/auth/login", json=creds)).status_code == 200
    page = (await client.get("/api/v1/applications")).json()
    return sorted((item["source"] for item in page["items"]), key=lambda s: s or "")


@pytest.mark.usefixtures("migrated_db", "bucket", "multi_mode")
async def test_apply_stores_a_valid_source_and_drops_an_invalid_one(client: AsyncClient) -> None:
    slug, job_slug, creds = await _register_with_job(client)
    await client.post("/api/v1/auth/logout")
    assert await _apply(client, slug, job_slug, source="link:newsletter") == 201
    assert await _apply(client, slug, job_slug, source="<script>alert(1)</script>") == 201
    assert await _apply(client, slug, job_slug) == 201
    assert await _apply(client, slug, job_slug, source="x" * 200) == 201
    assert await _sources_seen(client, creds) == [None, None, None, "link:newsletter"]
