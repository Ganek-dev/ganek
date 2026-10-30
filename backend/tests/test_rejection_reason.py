"""Optional internal rejection reason and note on an application (card
"Candidate emails", PR 2): stored by the stage writers, carried in the
stage.changed activity payload, cleared on reopening."""

import pytest
from httpx import AsyncClient

from app.core.config import settings
from tests.db import database_reachable, s3_reachable
from tests.test_bulk_reject import _company_with_applicants, _ids_by_email

pytestmark = pytest.mark.skipif(
    not (database_reachable() and s3_reachable()),
    reason="database and object storage required (start postgres+minio or use CI)",
)

NOTE = "Strong, but the other finalist had the Kubernetes depth."


@pytest.fixture
def multi_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "mode", "multi")


async def _one_applicant(client: AsyncClient) -> str:
    """Registers a company with one applicant; returns the application id."""
    applicants, _ = await _company_with_applicants(client, 1, name_prefix="Reason Co")
    return (await _ids_by_email(client))[applicants[0]["email"]]


async def _stage_moves(client: AsyncClient) -> list[dict[str, object]]:
    feed = (await client.get("/api/v1/activity")).json()
    return [row for row in feed if row["type"] == "stage.changed"]


@pytest.mark.usefixtures("migrated_db", "bucket", "multi_mode")
async def test_reject_with_reason_stores_it_and_logs_it(client: AsyncClient) -> None:
    app_id = await _one_applicant(client)
    resp = await client.patch(
        f"/api/v1/applications/{app_id}/stage",
        json={
            "stage": "rejected",
            "rejection_reason": "another_candidate",
            "rejection_note": f"  {NOTE}  ",
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["rejection_reason"] == "another_candidate"
    assert body["rejection_note"] == NOTE
    (move,) = await _stage_moves(client)
    assert move["payload"] == {
        "from": "new",
        "to": "rejected",
        "reason": "another_candidate",
        "note": NOTE,
    }


@pytest.mark.usefixtures("migrated_db", "bucket", "multi_mode")
async def test_reject_without_a_reason_stores_nulls(client: AsyncClient) -> None:
    app_id = await _one_applicant(client)
    resp = await client.patch(f"/api/v1/applications/{app_id}/stage", json={"stage": "rejected"})
    assert resp.status_code == 200, resp.text
    assert resp.json()["rejection_reason"] is None
    assert resp.json()["rejection_note"] is None
    (move,) = await _stage_moves(client)
    assert move["payload"] == {"from": "new", "to": "rejected"}


@pytest.mark.usefixtures("migrated_db", "bucket", "multi_mode")
async def test_reason_only_with_rejected(client: AsyncClient) -> None:
    app_id = await _one_applicant(client)
    resp = await client.patch(
        f"/api/v1/applications/{app_id}/stage",
        json={"stage": "screening", "rejection_reason": "skills_gap"},
    )
    assert resp.status_code == 422, resp.text
    row = (await client.get(f"/api/v1/applications/{app_id}")).json()
    assert row["stage"] == "new"
    assert row["rejection_reason"] is None


@pytest.mark.usefixtures("migrated_db", "bucket", "multi_mode")
async def test_unknown_reason_is_rejected(client: AsyncClient) -> None:
    app_id = await _one_applicant(client)
    resp = await client.patch(
        f"/api/v1/applications/{app_id}/stage",
        json={"stage": "rejected", "rejection_reason": "vibes"},
    )
    assert resp.status_code == 422, resp.text


@pytest.mark.usefixtures("migrated_db", "bucket", "multi_mode")
async def test_note_is_trimmed_and_capped(client: AsyncClient) -> None:
    app_id = await _one_applicant(client)
    url = f"/api/v1/applications/{app_id}/stage"
    resp = await client.patch(url, json={"stage": "rejected", "rejection_note": "   "})
    assert resp.status_code == 200, resp.text
    assert resp.json()["rejection_note"] is None

    await client.patch(url, json={"stage": "screening"})
    resp = await client.patch(url, json={"stage": "rejected", "rejection_note": "x" * 1001})
    assert resp.status_code == 422, resp.text
    assert (await client.get(f"/api/v1/applications/{app_id}")).json()["rejection_note"] is None

    resp = await client.patch(url, json={"stage": "rejected", "rejection_note": "x" * 1000})
    assert resp.status_code == 200, resp.text
    assert resp.json()["rejection_note"] == "x" * 1000


@pytest.mark.usefixtures("migrated_db", "bucket", "multi_mode")
async def test_reopening_clears_the_reason_but_history_keeps_it(client: AsyncClient) -> None:
    app_id = await _one_applicant(client)
    url = f"/api/v1/applications/{app_id}/stage"
    resp = await client.patch(
        url, json={"stage": "rejected", "rejection_reason": "other", "rejection_note": NOTE}
    )
    assert resp.status_code == 200, resp.text
    resp = await client.patch(url, json={"stage": "screening"})
    assert resp.status_code == 200, resp.text
    assert resp.json()["rejection_reason"] is None
    assert resp.json()["rejection_note"] is None
    row = (await client.get(f"/api/v1/applications/{app_id}")).json()
    assert row["rejection_reason"] is None and row["rejection_note"] is None

    moves = await _stage_moves(client)
    rejected = next(m for m in moves if m["payload"]["to"] == "rejected")  # type: ignore[index]
    assert rejected["payload"] == {
        "from": "new",
        "to": "rejected",
        "reason": "other",
        "note": NOTE,
    }
    reopened = next(m for m in moves if m["payload"]["to"] == "screening")  # type: ignore[index]
    assert reopened["payload"] == {"from": "rejected", "to": "screening"}


@pytest.mark.usefixtures("migrated_db", "bucket", "multi_mode")
async def test_bulk_reject_applies_the_reason_to_every_row(client: AsyncClient) -> None:
    applicants, _ = await _company_with_applicants(client, 2, name_prefix="Reason Co")
    ids = await _ids_by_email(client)
    a, b = (ids[app["email"]] for app in applicants)
    resp = await client.post(
        "/api/v1/applications/bulk-reject",
        json={
            "application_ids": [a, b],
            "rejection_reason": "skills_gap",
            "rejection_note": "Below the bar on the take-home",
        },
    )
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"rejected": 2, "skipped": 0}
    for app_id in (a, b):
        row = (await client.get(f"/api/v1/applications/{app_id}")).json()
        assert row["rejection_reason"] == "skills_gap"
        assert row["rejection_note"] == "Below the bar on the take-home"
    moves = await _stage_moves(client)
    assert len(moves) == 2
    assert all(
        m["payload"]
        == {
            "from": "new",
            "to": "rejected",
            "bulk": True,
            "reason": "skills_gap",
            "note": "Below the bar on the take-home",
        }
        for m in moves
    )


@pytest.mark.usefixtures("migrated_db", "bucket", "multi_mode")
async def test_bulk_stage_to_rejected_takes_the_reason_and_other_stages_refuse_it(
    client: AsyncClient,
) -> None:
    applicants, _ = await _company_with_applicants(client, 2, name_prefix="Reason Co")
    ids = await _ids_by_email(client)
    a, b = (ids[app["email"]] for app in applicants)
    resp = await client.post(
        "/api/v1/applications/bulk-stage",
        json={"application_ids": [a, b], "stage": "screening", "rejection_reason": "no_response"},
    )
    assert resp.status_code == 422, resp.text
    assert (await client.get(f"/api/v1/applications/{a}")).json()["stage"] == "new"

    resp = await client.post(
        "/api/v1/applications/bulk-stage",
        json={"application_ids": [a, b], "stage": "rejected", "rejection_reason": "no_response"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"updated": 2, "skipped": 0}
    for app_id in (a, b):
        row = (await client.get(f"/api/v1/applications/{app_id}")).json()
        assert row["stage"] == "rejected"
        assert row["rejection_reason"] == "no_response"
        assert row["rejection_note"] is None
    moves = await _stage_moves(client)
    assert all(
        m["payload"] == {"from": "new", "to": "rejected", "bulk": True, "reason": "no_response"}
        for m in moves
    )
