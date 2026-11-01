"""Workspace stage limit (pipeline signals): PATCH /company/settings accepts
stage_limit_days 1-60, null resets, and stage_limit() falls back to 7."""

from uuid import uuid4

import pytest
from httpx import AsyncClient

from app.core.config import settings
from app.models.company import Company
from app.services.pipeline_signals import DEFAULT_STAGE_LIMIT_DAYS, STAGE_LIMIT_KEY, stage_limit
from tests.db import database_reachable

needs_db = pytest.mark.skipif(
    not database_reachable(), reason="database not reachable (start postgres or use CI)"
)


@pytest.fixture
def multi_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "mode", "multi")


async def _register_admin(client: AsyncClient) -> None:
    resp = await client.post(
        "/api/v1/auth/register",
        json={
            "company_name": f"Pipeline Co {uuid4().hex[:6]}",
            "email": f"admin-{uuid4().hex[:8]}@ganek-ci.dev",
            "password": "a-long-secure-password",
        },
    )
    assert resp.status_code == 201, resp.text


def test_stage_limit_defaults_to_seven() -> None:
    assert DEFAULT_STAGE_LIMIT_DAYS == 7
    assert stage_limit(Company(name="x", slug="x", settings=None)) == 7
    assert stage_limit(Company(name="x", slug="x", settings={})) == 7
    assert stage_limit(Company(name="x", slug="x", settings={STAGE_LIMIT_KEY: 21})) == 21


@needs_db
@pytest.mark.usefixtures("migrated_db", "multi_mode")
async def test_patch_accepts_14_and_summary_carries_it(client: AsyncClient) -> None:
    await _register_admin(client)
    resp = await client.patch("/api/v1/company/settings", json={"stage_limit_days": 14})
    assert resp.status_code == 200, resp.text
    assert (await client.get("/api/v1/company")).json()["settings"]["stage_limit_days"] == 14


@needs_db
@pytest.mark.usefixtures("migrated_db", "multi_mode")
async def test_patch_rejects_out_of_bounds(client: AsyncClient) -> None:
    await _register_admin(client)
    for bad in (0, 61):
        resp = await client.patch("/api/v1/company/settings", json={"stage_limit_days": bad})
        assert resp.status_code == 422, resp.text


@needs_db
@pytest.mark.usefixtures("migrated_db", "multi_mode")
async def test_patch_null_resets(client: AsyncClient) -> None:
    await _register_admin(client)
    await client.patch("/api/v1/company/settings", json={"stage_limit_days": 14})
    resp = await client.patch("/api/v1/company/settings", json={"stage_limit_days": None})
    assert resp.status_code == 200, resp.text
    stored = (await client.get("/api/v1/company")).json()["settings"]
    assert STAGE_LIMIT_KEY not in stored
    assert stage_limit(Company(name="x", slug="x", settings=stored)) == 7
