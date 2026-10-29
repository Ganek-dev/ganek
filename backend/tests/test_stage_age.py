"""Stage age (board card "Candidate timeline", deferred from "Applicant
list"): applications.stage_changed_at moves with the stage and drives the
"longest in stage" sort keys."""

import pytest
from httpx import AsyncClient

from app.core.config import settings
from tests.db import database_reachable, s3_reachable
from tests.test_bulk_reject import _company_with_applicants, _ids_by_email

pytestmark = pytest.mark.skipif(
    not (database_reachable() and s3_reachable()),
    reason="database and object storage required (start postgres+minio or use CI)",
)


@pytest.fixture
def multi_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "mode", "multi")


async def _order(client: AsyncClient, sort: str) -> list[str]:
    resp = await client.get("/api/v1/applications", params={"sort": sort})
    assert resp.status_code == 200, resp.text
    return [row["id"] for row in resp.json()["items"]]


@pytest.mark.usefixtures("migrated_db", "bucket", "multi_mode")
async def test_stage_changed_at_moves_only_on_a_real_change(client: AsyncClient) -> None:
    applicants, _ = await _company_with_applicants(client, 1)
    app_id = (await _ids_by_email(client))[applicants[0]["email"]]
    before = (await client.get(f"/api/v1/applications/{app_id}")).json()
    assert before["stage_changed_at"] == before["created_at"]

    same = await client.patch(f"/api/v1/applications/{app_id}/stage", json={"stage": "new"})
    assert same.status_code == 200 and same.json()["stage_changed_at"] == before["created_at"]

    moved = await client.patch(f"/api/v1/applications/{app_id}/stage", json={"stage": "screening"})
    assert moved.status_code == 200
    assert moved.json()["stage_changed_at"] > before["created_at"]


@pytest.mark.usefixtures("migrated_db", "bucket", "multi_mode")
async def test_sort_by_time_in_stage(client: AsyncClient) -> None:
    applicants, _ = await _company_with_applicants(client, 3)
    ids = await _ids_by_email(client)
    a, b, c = (ids[app["email"]] for app in applicants)
    assert (
        await client.patch(f"/api/v1/applications/{b}/stage", json={"stage": "screening"})
    ).status_code == 200

    assert await _order(client, "stage_age_desc") == [a, c, b]  # longest in stage first
    assert await _order(client, "stage_age_asc") == [b, c, a]
    assert (
        await client.get("/api/v1/applications", params={"sort": "sideways"})
    ).status_code == 422
