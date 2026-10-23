"""Per-company API keys (card D4, part A): admin-managed, hashed at rest,
bearer credential for the read endpoints (and the stage PATCH with scope
write), tenant-scoped like a session."""

from uuid import uuid4

import pytest
from httpx import AsyncClient

from app.core.config import settings
from tests.db import database_reachable, s3_reachable
from tests.test_admin_applications_api import _company_with_applicant

pytestmark = pytest.mark.skipif(
    not (database_reachable() and s3_reachable()),
    reason="database and object storage required (start postgres+minio or use CI)",
)


@pytest.fixture
def multi_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "mode", "multi")


async def _register(client: AsyncClient) -> None:
    resp = await client.post(
        "/api/v1/auth/register",
        json={
            "company_name": f"Keys Co {uuid4().hex[:6]}",
            "email": f"admin-{uuid4().hex[:8]}@ganek-ci.dev",
            "password": "a-long-secure-password",
        },
    )
    assert resp.status_code == 201, resp.text


@pytest.mark.usefixtures("migrated_db", "multi_mode")
async def test_admin_creates_lists_and_revokes_keys(client: AsyncClient) -> None:
    await _register(client)
    created = await client.post("/api/v1/api-keys", json={"name": "Zapier", "scope": "read"})
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["secret"].startswith("gk_") and len(body["secret"]) >= 40
    assert body["prefix"] == body["secret"][:12]
    assert body["scope"] == "read" and body["name"] == "Zapier"

    listed = (await client.get("/api/v1/api-keys")).json()
    assert [k["prefix"] for k in listed] == [body["prefix"]]
    assert "secret" not in listed[0] and "key_hash" not in listed[0]
    assert listed[0]["revoked_at"] is None and listed[0]["last_used_at"] is None

    assert (await client.delete(f"/api/v1/api-keys/{body['id']}")).status_code == 204
    listed = (await client.get("/api/v1/api-keys")).json()
    assert listed[0]["revoked_at"] is not None
    # revoking twice and unknown ids are 404
    assert (await client.delete(f"/api/v1/api-keys/{body['id']}")).status_code == 404
    assert (await client.delete(f"/api/v1/api-keys/{uuid4()}")).status_code == 404

    types = [a["type"] for a in (await client.get("/api/v1/activity")).json()]
    assert types[:2] == ["api_key.revoked", "api_key.created"]


@pytest.mark.usefixtures("migrated_db", "bucket", "multi_mode")
async def test_read_key_lists_applications_and_leaks_nothing(client: AsyncClient) -> None:
    await _company_with_applicant(client, with_quiz=True)
    secret = (
        await client.post("/api/v1/api-keys", json={"name": "ATS sync", "scope": "read"})
    ).json()["secret"]
    await client.post("/api/v1/auth/logout")
    bearer = {"Authorization": f"Bearer {secret}"}

    assert (await client.get("/api/v1/applications")).status_code == 401
    resp = await client.get("/api/v1/applications", headers=bearer)
    assert resp.status_code == 200, resp.text
    page = resp.json()
    assert page["total"] == 1 and page["items"][0]["candidate"]["name"] == "Jane Applicant"
    assert "correct_key" not in resp.text
    app_id = page["items"][0]["id"]
    assert (await client.get(f"/api/v1/applications/{app_id}", headers=bearer)).status_code == 200
    assert (await client.get(f"/api/v1/applications/{uuid4()}", headers=bearer)).status_code == 404
    export = await client.get("/api/v1/applications/export?format=json", headers=bearer)
    assert export.status_code == 200 and len(export.json()) == 1

    # read scope stops at writes; sessions-only routes stay closed to keys
    assert (
        await client.patch(
            f"/api/v1/applications/{app_id}/stage", json={"stage": "screening"}, headers=bearer
        )
    ).status_code == 403
    assert (await client.get("/api/v1/api-keys", headers=bearer)).status_code == 401
    assert (
        await client.get(
            "/api/v1/applications", headers={"Authorization": "Bearer gk_not_a_real_key"}
        )
    ).status_code == 401

    assert (await client.get("/api/v1/applications", headers=bearer)).status_code == 200


@pytest.mark.usefixtures("migrated_db", "bucket", "multi_mode")
async def test_write_key_changes_stage_and_revocation_bites(client: AsyncClient) -> None:
    await _company_with_applicant(client)
    created = (
        await client.post("/api/v1/api-keys", json={"name": "Workflow", "scope": "write"})
    ).json()
    bearer = {"Authorization": f"Bearer {created['secret']}"}
    app_id = (await client.get("/api/v1/applications")).json()["items"][0]["id"]

    resp = await client.patch(
        f"/api/v1/applications/{app_id}/stage", json={"stage": "screening"}, headers=bearer
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["stage"] == "screening"
    activity = (await client.get("/api/v1/activity")).json()
    moved = next(a for a in activity if a["type"] == "stage.changed")
    assert moved["actor_email"] is None  # a key, not a person

    listed = (await client.get("/api/v1/api-keys")).json()
    assert listed[0]["last_used_at"] is not None

    assert (await client.delete(f"/api/v1/api-keys/{created['id']}")).status_code == 204
    assert (await client.get("/api/v1/applications", headers=bearer)).status_code == 401
