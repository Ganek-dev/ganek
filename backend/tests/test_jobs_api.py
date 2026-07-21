from collections.abc import Awaitable, Callable
from uuid import uuid4

import pytest
from httpx import AsyncClient

from app.core.config import settings
from tests.db import database_reachable

pytestmark = pytest.mark.skipif(
    not database_reachable(), reason="database not reachable (start postgres or use CI)"
)

RegisterFn = Callable[[AsyncClient], Awaitable[None]]


@pytest.fixture
def multi_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "mode", "multi")


async def _register(client: AsyncClient) -> None:
    resp = await client.post(
        "/api/v1/auth/register",
        json={
            "company_name": f"Jobs Co {uuid4().hex[:6]}",
            "email": f"admin-{uuid4().hex[:8]}@vetd-ci.dev",
            "password": "a-long-secure-password",
        },
    )
    assert resp.status_code == 201, resp.text


def _job_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "title": "Senior Python Developer",
        "description_md": "We build **things**.",
        "location": "Warsaw",
        "remote_policy": "hybrid",
        "employment_type": "full_time",
        "salary_min": 15000,
        "salary_max": 25000,
        "salary_currency": "PLN",
        "tags": ["python", "fastapi", "backend"],
    }
    payload.update(overrides)
    return payload


@pytest.mark.usefixtures("migrated_db", "multi_mode")
async def test_job_crud_lifecycle(client: AsyncClient) -> None:
    await _register(client)

    resp = await client.post("/api/v1/jobs", json=_job_payload())
    assert resp.status_code == 201, resp.text
    job = resp.json()
    assert job["slug"] == "senior-python-developer"
    assert job["status"] == "draft"
    assert job["published_at"] is None

    resp = await client.get("/api/v1/jobs")
    assert [j["id"] for j in resp.json()] == [job["id"]]

    resp = await client.patch(f"/api/v1/jobs/{job['id']}", json={"title": "Staff Python Dev"})
    assert resp.status_code == 200
    assert resp.json()["title"] == "Staff Python Dev"
    assert resp.json()["slug"] == "senior-python-developer"  # slug is stable

    resp = await client.post(f"/api/v1/jobs/{job['id']}/publish")
    assert resp.status_code == 200
    assert resp.json()["status"] == "published"
    assert resp.json()["published_at"] is not None

    # published job cannot be deleted
    resp = await client.delete(f"/api/v1/jobs/{job['id']}")
    assert resp.status_code == 409

    resp = await client.post(f"/api/v1/jobs/{job['id']}/close")
    assert resp.status_code == 200
    assert resp.json()["status"] == "closed"

    # closed can be re-published
    resp = await client.post(f"/api/v1/jobs/{job['id']}/publish")
    assert resp.status_code == 200


@pytest.mark.usefixtures("migrated_db", "multi_mode")
async def test_duplicate_titles_get_unique_slugs(client: AsyncClient) -> None:
    await _register(client)
    first = (await client.post("/api/v1/jobs", json=_job_payload())).json()
    second = (await client.post("/api/v1/jobs", json=_job_payload())).json()
    assert first["slug"] != second["slug"]
    assert second["slug"].startswith("senior-python-developer-")


@pytest.mark.usefixtures("migrated_db", "multi_mode")
async def test_invalid_salary_range_rejected(client: AsyncClient) -> None:
    await _register(client)
    resp = await client.post("/api/v1/jobs", json=_job_payload(salary_min=30000, salary_max=20000))
    assert resp.status_code == 422


@pytest.mark.usefixtures("migrated_db", "multi_mode")
async def test_draft_job_deletable(client: AsyncClient) -> None:
    await _register(client)
    job = (await client.post("/api/v1/jobs", json=_job_payload())).json()
    resp = await client.delete(f"/api/v1/jobs/{job['id']}")
    assert resp.status_code == 204
    assert (await client.get(f"/api/v1/jobs/{job['id']}")).status_code == 404


@pytest.mark.usefixtures("migrated_db", "multi_mode")
async def test_jobs_require_auth(client: AsyncClient) -> None:
    assert (await client.get("/api/v1/jobs")).status_code == 401
    assert (await client.post("/api/v1/jobs", json=_job_payload())).status_code == 401


@pytest.mark.usefixtures("migrated_db", "multi_mode")
async def test_tenant_isolation(client: AsyncClient) -> None:
    await _register(client)
    job = (await client.post("/api/v1/jobs", json=_job_payload())).json()

    # second company cannot see or touch the first company's job
    await client.post("/api/v1/auth/logout")
    await _register(client)
    assert (await client.get(f"/api/v1/jobs/{job['id']}")).status_code == 404
    assert (await client.patch(f"/api/v1/jobs/{job['id']}", json={"title": "X"})).status_code == 404
    assert (await client.get("/api/v1/jobs")).json() == []
