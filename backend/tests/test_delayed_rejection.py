"""Delayed rejection mail: send_after on the stage, bulk-reject and
bulk-stage routes holds the mail as a scheduled outbox row; bad values are a
422 with nothing moved."""

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from httpx import AsyncClient

from app.core.config import settings
from app.services import email as email_service
from tests.db import database_reachable, s3_reachable
from tests.test_bulk_reject import _company_with_applicants, _ids_by_email

pytestmark = pytest.mark.skipif(
    not (database_reachable() and s3_reachable()),
    reason="database and object storage required (start postgres+minio or use CI)",
)


@pytest.fixture
def multi_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "mode", "multi")


@pytest.fixture
def sent(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    captured: list[dict[str, Any]] = []
    monkeypatch.setattr(email_service, "send_rejection", lambda **kw: captured.append(kw))
    return captured


def _when(**delta: float) -> str:
    return (datetime.now(UTC) + timedelta(**delta)).isoformat()


async def _emails(client: AsyncClient, app_id: str) -> list[dict[str, Any]]:
    resp = await client.get(f"/api/v1/applications/{app_id}/emails")
    assert resp.status_code == 200, resp.text
    # the "application received" mail is in the trail too; only rejections matter
    return [row for row in resp.json() if row["kind"] == "rejection"]


async def _stage_of(client: AsyncClient, app_id: str) -> str:
    items = (await client.get("/api/v1/applications")).json()["items"]
    return str(next(item["stage"] for item in items if item["id"] == app_id))


@pytest.mark.usefixtures("migrated_db", "bucket", "multi_mode")
async def test_single_reject_with_send_after_schedules_and_does_not_send(
    client: AsyncClient, sent: list[dict[str, Any]]
) -> None:
    applicants, _ = await _company_with_applicants(client, 1)
    app_id = (await _ids_by_email(client))[applicants[0]["email"]]
    when = _when(days=1)

    resp = await client.patch(
        f"/api/v1/applications/{app_id}/stage",
        json={"stage": "rejected", "notify_candidate": True, "send_after": when},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["stage"] == "rejected"
    assert sent == []
    rows = await _emails(client, app_id)
    assert len(rows) == 1
    assert rows[0]["status"] == "scheduled"
    assert rows[0]["kind"] == "rejection"
    assert datetime.fromisoformat(rows[0]["send_after"]) == datetime.fromisoformat(when)


_BAD: list[Callable[[], str]] = [
    lambda: "2026-11-02T09:00:00",
    lambda: _when(minutes=-1),
    lambda: _when(days=15),
]


@pytest.mark.usefixtures("migrated_db", "bucket", "multi_mode")
@pytest.mark.parametrize("make_bad", _BAD, ids=["naive", "past", "too_far"])
async def test_bad_send_after_is_422_and_moves_nothing(
    client: AsyncClient, make_bad: Callable[[], str]
) -> None:
    applicants, _ = await _company_with_applicants(client, 1)
    app_id = (await _ids_by_email(client))[applicants[0]["email"]]
    before = await _stage_of(client, app_id)

    resp = await client.patch(
        f"/api/v1/applications/{app_id}/stage",
        json={"stage": "rejected", "notify_candidate": True, "send_after": make_bad()},
    )
    assert resp.status_code == 422
    assert await _stage_of(client, app_id) == before


@pytest.mark.usefixtures("migrated_db", "bucket", "multi_mode")
async def test_send_after_needs_the_rejected_stage(client: AsyncClient) -> None:
    applicants, _ = await _company_with_applicants(client, 1)
    app_id = (await _ids_by_email(client))[applicants[0]["email"]]
    when = _when(days=1)

    resp = await client.patch(
        f"/api/v1/applications/{app_id}/stage",
        json={"stage": "interview", "notify_candidate": True, "send_after": when},
    )
    assert resp.status_code == 422
    resp = await client.post(
        "/api/v1/applications/bulk-stage",
        json={
            "application_ids": [app_id],
            "stage": "interview",
            "notify_candidates": True,
            "send_after": when,
        },
    )
    assert resp.status_code == 422
    assert await _stage_of(client, app_id) == "new"


@pytest.mark.usefixtures("migrated_db", "bucket", "multi_mode")
async def test_bulk_reject_and_bulk_stage_schedule_alike(
    client: AsyncClient, sent: list[dict[str, Any]]
) -> None:
    applicants, _ = await _company_with_applicants(client, 2)
    ids = await _ids_by_email(client)
    a, b = (ids[app["email"]] for app in applicants)
    when = _when(days=2)

    resp = await client.post(
        "/api/v1/applications/bulk-reject",
        json={"application_ids": [a], "notify_candidates": True, "send_after": when},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"rejected": 1, "skipped": 0}
    resp = await client.post(
        "/api/v1/applications/bulk-stage",
        json={
            "application_ids": [b],
            "stage": "rejected",
            "notify_candidates": True,
            "send_after": when,
        },
    )
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"updated": 1, "skipped": 0}

    assert sent == []
    for app_id in (a, b):
        rows = await _emails(client, app_id)
        assert [(r["kind"], r["status"]) for r in rows] == [("rejection", "scheduled")]
        assert datetime.fromisoformat(rows[0]["send_after"]) == datetime.fromisoformat(when)


@pytest.mark.usefixtures("migrated_db", "bucket", "multi_mode")
async def test_send_now_is_unchanged(client: AsyncClient, sent: list[dict[str, Any]]) -> None:
    applicants, _ = await _company_with_applicants(client, 1)
    app_id = (await _ids_by_email(client))[applicants[0]["email"]]

    resp = await client.patch(
        f"/api/v1/applications/{app_id}/stage",
        json={"stage": "rejected", "notify_candidate": True},
    )
    assert resp.status_code == 200, resp.text
    assert len(sent) == 1
    rows = await _emails(client, app_id)
    assert [(r["kind"], r["status"]) for r in rows] == [("rejection", "sent")]
    assert rows[0]["send_after"] is None
