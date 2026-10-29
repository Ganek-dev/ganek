"""Bulk stage change (board card "Applicant list", bulk bar "Move to"):
moves every open row the actor may touch, skips the rest, one activity
entry per moved row so the coming timeline can show who moved whom."""

from uuid import uuid4

import pytest
from httpx import AsyncClient

from app.core.config import settings
from tests.db import database_reachable, s3_reachable
from tests.test_bulk_reject import _company_with_applicants, _ids_by_email, _register_company

pytestmark = pytest.mark.skipif(
    not (database_reachable() and s3_reachable()),
    reason="database and object storage required (start postgres+minio or use CI)",
)


@pytest.fixture
def multi_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "mode", "multi")


@pytest.mark.usefixtures("migrated_db", "bucket", "multi_mode")
async def test_bulk_stage_moves_open_rows_and_reports_counts(client: AsyncClient) -> None:
    applicants, _ = await _company_with_applicants(client, 3)
    ids = await _ids_by_email(client)
    a, b, c = (ids[app["email"]] for app in applicants)

    resp = await client.post(
        "/api/v1/applications/bulk-stage",
        json={"application_ids": [a, b], "stage": "screening"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"updated": 2, "skipped": 0}

    stages = {
        app["id"]: app["stage"]
        for app in (await client.get("/api/v1/applications")).json()["items"]
    }
    assert stages == {a: "screening", b: "screening", c: "new"}


@pytest.mark.usefixtures("migrated_db", "bucket", "multi_mode")
async def test_bulk_stage_skips_unchanged_and_withdrawn(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.services import email as email_service

    sent: list[dict[str, object]] = []
    monkeypatch.setattr(email_service, "send_stage_advance", lambda **kw: sent.append(kw))

    applicants, creds = await _company_with_applicants(client, 3)
    ids = await _ids_by_email(client)
    already_there, withdrawn, open_row = (ids[app["email"]] for app in applicants)
    assert (
        await client.patch(
            f"/api/v1/applications/{already_there}/stage", json={"stage": "interview"}
        )
    ).status_code == 200
    await client.post("/api/v1/auth/logout")
    assert (
        await client.post(f"/api/v1/public/applications/{applicants[1]['status_token']}/withdraw")
    ).status_code == 200
    assert (await client.post("/api/v1/auth/login", json=creds)).status_code == 200

    resp = await client.post(
        "/api/v1/applications/bulk-stage",
        json={
            "application_ids": [already_there, withdrawn, open_row, str(uuid4())],
            "stage": "interview",
            "notify_candidates": True,
        },
    )
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"updated": 1, "skipped": 3}
    stages = {
        app["id"]: app["stage"]
        for app in (await client.get("/api/v1/applications")).json()["items"]
    }
    assert stages[withdrawn] == "withdrawn"
    assert stages[already_there] == "interview"
    assert stages[open_row] == "interview"
    # only the row that actually moved hears about it
    assert [mail["to"] for mail in sent] == [applicants[2]["email"]]


@pytest.mark.usefixtures("migrated_db", "bucket", "multi_mode")
async def test_bulk_stage_is_tenant_scoped(client: AsyncClient) -> None:
    applicants, creds = await _company_with_applicants(client, 1)
    own = (await _ids_by_email(client))[applicants[0]["email"]]
    foreign_applicants, foreign_creds = await _company_with_applicants(
        client, 1, name_prefix="Foreign Co"
    )
    foreign = (await _ids_by_email(client))[foreign_applicants[0]["email"]]
    await client.post("/api/v1/auth/logout")
    assert (await client.post("/api/v1/auth/login", json=creds)).status_code == 200

    resp = await client.post(
        "/api/v1/applications/bulk-stage",
        json={"application_ids": [own, foreign], "stage": "rejected"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"updated": 1, "skipped": 1}

    await client.post("/api/v1/auth/logout")
    assert (await client.post("/api/v1/auth/login", json=foreign_creds)).status_code == 200
    foreign_stage = (await client.get("/api/v1/applications")).json()["items"][0]["stage"]
    assert foreign_stage == "new"


@pytest.mark.usefixtures("migrated_db", "bucket", "multi_mode")
async def test_bulk_stage_rejects_withdrawn_target_and_the_cap(client: AsyncClient) -> None:
    await _register_company(client, "Cap Co")
    resp = await client.post(
        "/api/v1/applications/bulk-stage",
        json={"application_ids": [str(uuid4())], "stage": "withdrawn"},
    )
    assert resp.status_code == 422
    resp = await client.post(
        "/api/v1/applications/bulk-stage",
        json={"application_ids": [str(uuid4()) for _ in range(101)], "stage": "screening"},
    )
    assert resp.status_code == 422


@pytest.mark.usefixtures("migrated_db", "bucket", "multi_mode")
async def test_bulk_stage_emails_only_when_asked(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.services import email as email_service

    rejections: list[dict[str, object]] = []
    monkeypatch.setattr(email_service, "send_rejection", lambda **kw: rejections.append(kw))

    applicants, _ = await _company_with_applicants(client, 2)
    ids = await _ids_by_email(client)
    a, b = (ids[app["email"]] for app in applicants)

    resp = await client.post(
        "/api/v1/applications/bulk-stage", json={"application_ids": [a], "stage": "rejected"}
    )
    assert resp.status_code == 200 and resp.json() == {"updated": 1, "skipped": 0}
    assert rejections == []

    resp = await client.post(
        "/api/v1/applications/bulk-stage",
        json={"application_ids": [a, b], "stage": "rejected", "notify_candidates": True},
    )
    assert resp.status_code == 200 and resp.json() == {"updated": 1, "skipped": 1}
    assert [mail["to"] for mail in rejections] == [applicants[1]["email"]]


@pytest.mark.usefixtures("migrated_db", "bucket", "multi_mode")
async def test_bulk_stage_records_activity_per_row(client: AsyncClient) -> None:
    applicants, _ = await _company_with_applicants(client, 2)
    ids = await _ids_by_email(client)
    a, b = (ids[app["email"]] for app in applicants)

    resp = await client.post(
        "/api/v1/applications/bulk-stage",
        json={"application_ids": [a, b], "stage": "screening"},
    )
    assert resp.status_code == 200

    feed = (await client.get("/api/v1/activity")).json()
    moves = [row for row in feed if row["type"] == "stage.changed"]
    assert len(moves) == 2
    assert all(row["payload"] == {"from": "new", "to": "screening", "bulk": True} for row in moves)
