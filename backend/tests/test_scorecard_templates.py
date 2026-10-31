"""Scorecard templates (spec SCORECARDS_SPEC): the company default is written
by admins through PATCH /company/settings, copied into new jobs, and each job's
template is editable by any member."""

from uuid import uuid4

import pytest
from httpx import AsyncClient

from app.core.config import settings
from tests.db import database_reachable

pytestmark = pytest.mark.skipif(
    not database_reachable(), reason="database not reachable (start postgres or use CI)"
)

TEMPLATE = [{"label": "Problem solving", "hint": "Breaks work down"}, {"label": "Communication"}]


@pytest.fixture
def multi_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "mode", "multi")


async def _register_admin(client: AsyncClient) -> None:
    resp = await client.post(
        "/api/v1/auth/register",
        json={
            "company_name": f"Scorecard Co {uuid4().hex[:6]}",
            "email": f"admin-{uuid4().hex[:8]}@ganek-ci.dev",
            "password": "a-long-secure-password",
        },
    )
    assert resp.status_code == 201, resp.text


async def _switch_to_member(client: AsyncClient) -> None:
    email = f"member-{uuid4().hex[:8]}@ganek-ci.dev"
    password = "member-password-1234"
    resp = await client.post(
        "/api/v1/users", json={"email": email, "password": password, "role": "member"}
    )
    assert resp.status_code == 201, resp.text
    await client.post("/api/v1/auth/logout")
    resp = await client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert resp.status_code == 200, resp.text


async def _patch_settings(client: AsyncClient, template: list[dict[str, str]]) -> None:
    resp = await client.patch("/api/v1/company/settings", json={"scorecard_template": template})
    assert resp.status_code == 200, resp.text


async def _create_job(client: AsyncClient, **extra: object) -> dict[str, object]:
    resp = await client.post("/api/v1/jobs", json={"title": "Backend Engineer", **extra})
    assert resp.status_code == 201, resp.text
    return resp.json()  # type: ignore[no-any-return]


@pytest.mark.usefixtures("migrated_db", "multi_mode")
async def test_settings_patch_assigns_ids_and_round_trips(client: AsyncClient) -> None:
    await _register_admin(client)
    await _patch_settings(client, TEMPLATE)
    saved = (await client.get("/api/v1/company")).json()["scorecard_template"]
    assert [c["label"] for c in saved] == ["Problem solving", "Communication"]
    assert saved[0]["hint"] == "Breaks work down"
    assert all(len(c["id"]) == 8 for c in saved)
    assert saved[0]["id"] != saved[1]["id"]


@pytest.mark.usefixtures("migrated_db", "multi_mode")
async def test_settings_patch_rejects_21_criteria(client: AsyncClient) -> None:
    await _register_admin(client)
    too_many = [{"label": f"c{i}"} for i in range(21)]
    resp = await client.patch("/api/v1/company/settings", json={"scorecard_template": too_many})
    assert resp.status_code == 422, resp.text


@pytest.mark.usefixtures("migrated_db", "multi_mode")
async def test_settings_patch_rejects_blank_label(client: AsyncClient) -> None:
    await _register_admin(client)
    resp = await client.patch(
        "/api/v1/company/settings", json={"scorecard_template": [{"label": ""}]}
    )
    assert resp.status_code == 422, resp.text


@pytest.mark.usefixtures("migrated_db", "multi_mode")
async def test_settings_patch_rejects_duplicate_ids(client: AsyncClient) -> None:
    await _register_admin(client)
    dup = [{"id": "same", "label": "A"}, {"id": "same", "label": "B"}]
    resp = await client.patch("/api/v1/company/settings", json={"scorecard_template": dup})
    assert resp.status_code == 422, resp.text


@pytest.mark.usefixtures("migrated_db", "multi_mode")
async def test_job_create_copies_company_default(client: AsyncClient) -> None:
    await _register_admin(client)
    await _patch_settings(client, TEMPLATE)
    default = (await client.get("/api/v1/company")).json()["scorecard_template"]
    job = await _create_job(client)
    assert job["scorecard_template"] == default


@pytest.mark.usefixtures("migrated_db", "multi_mode")
async def test_job_create_with_explicit_template_wins(client: AsyncClient) -> None:
    await _register_admin(client)
    await _patch_settings(client, TEMPLATE)
    job = await _create_job(client, scorecard_template=[{"label": "Only one"}])
    assert [c["label"] for c in job["scorecard_template"]] == ["Only one"]  # type: ignore[attr-defined]
    assert len(job["scorecard_template"][0]["id"]) == 8  # type: ignore[index]


@pytest.mark.usefixtures("migrated_db", "multi_mode")
async def test_job_patch_replaces_and_omit_keeps(client: AsyncClient) -> None:
    await _register_admin(client)
    await _patch_settings(client, TEMPLATE)
    job = await _create_job(client)
    url = f"/api/v1/jobs/{job['id']}"
    resp = await client.patch(url, json={"title": "Renamed"})
    assert resp.status_code == 200, resp.text
    assert resp.json()["scorecard_template"] == job["scorecard_template"]
    resp = await client.patch(url, json={"scorecard_template": []})
    assert resp.status_code == 200, resp.text
    assert resp.json()["scorecard_template"] == []


@pytest.mark.usefixtures("migrated_db", "multi_mode")
async def test_member_can_edit_job_template_but_not_company_default(client: AsyncClient) -> None:
    await _register_admin(client)
    job = await _create_job(client)
    await _switch_to_member(client)
    resp = await client.patch(
        f"/api/v1/jobs/{job['id']}", json={"scorecard_template": [{"label": "Craft"}]}
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["scorecard_template"][0]["label"] == "Craft"
    resp = await client.patch("/api/v1/company/settings", json={"scorecard_template": []})
    assert resp.status_code == 403, resp.text
