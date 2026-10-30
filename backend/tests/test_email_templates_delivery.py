"""Templates reach the mail (card "Candidate emails", PR 3): the outbox
snapshots the resolved subject and body at queue time, the senders render
the snapshot, the preview by template equals the delivered mail."""

from typing import Any
from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models import EmailOutbox
from app.services import email as email_service
from app.services import email_render
from app.services import outbox as outbox_service
from tests.db import database_reachable, s3_reachable
from tests.test_bulk_reject import _company_with_applicants, _ids_by_email
from tests.test_email_preview_api import _company_with_applicant

pytestmark = pytest.mark.skipif(
    not (database_reachable() and s3_reachable()),
    reason="database and object storage required (start postgres+minio or use CI)",
)

BASE = "/api/v1/company/email-templates"


@pytest.fixture
def multi_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "mode", "multi")


@pytest.fixture
def sent(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """Every mail the senders hand to the transport, as send_email kwargs."""
    captured: list[dict[str, Any]] = []
    monkeypatch.setattr(email_service, "send_email", lambda **kw: captured.append(kw))
    return captured


async def _template(
    client: AsyncClient, kind: str = "rejection", *, default: bool = False, **overrides: str
) -> dict[str, Any]:
    payload = {
        "kind": kind,
        "name": f"Custom {uuid4().hex[:4]}",
        "subject": "Custom {{company_name}}",
        "body": "Hello {{candidate_first_name}}\n\nCustom body.",
        **overrides,
    }
    resp = await client.post(BASE, json=payload)
    assert resp.status_code == 201, resp.text
    row: dict[str, Any] = resp.json()
    if default:
        assert (await client.post(f"{BASE}/{row['id']}/default")).status_code == 200
    return row


async def _rows(
    db: AsyncSession, application_id: str, kind: str = "rejection"
) -> list[EmailOutbox]:
    """The outbox rows of one kind (the apply flow also queues a confirmation)."""
    result = await db.execute(
        select(EmailOutbox)
        .where(EmailOutbox.application_id == application_id, EmailOutbox.kind == kind)
        .order_by(EmailOutbox.created_at)
    )
    return list(result.scalars().all())


async def _reject(client: AsyncClient, app_id: str, **extra: Any) -> Any:
    return await client.patch(
        f"/api/v1/applications/{app_id}/stage",
        json={"stage": "rejected", "notify_candidate": True, **extra},
    )


@pytest.mark.usefixtures("migrated_db", "bucket", "multi_mode", "sent")
async def test_queue_snapshots_the_default_template(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    app_id, _ = await _company_with_applicant(client)
    template = await _template(client, default=True)
    assert (await _reject(client, app_id)).status_code == 200
    (row,) = await _rows(db_session, app_id)
    assert row.kind == "rejection"
    assert row.payload["template_id"] == template["id"]
    assert row.payload["template_subject"] == "Custom {{company_name}}"
    assert row.payload["template_body"] == "Hello {{candidate_first_name}}\n\nCustom body."


@pytest.mark.usefixtures("migrated_db", "bucket", "multi_mode", "sent")
async def test_queue_snapshots_the_builtin_when_no_default(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    app_id, _ = await _company_with_applicant(client)
    assert (await _reject(client, app_id)).status_code == 200
    (row,) = await _rows(db_session, app_id)
    assert row.payload["template_id"] is None
    assert row.payload["template_subject"] == email_render.BUILTIN["rejection"].subject
    assert row.payload["template_body"] == email_render.BUILTIN["rejection"].body


@pytest.mark.usefixtures("migrated_db", "bucket", "multi_mode", "sent")
async def test_explicit_template_id_wins_over_the_default(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    app_id, _ = await _company_with_applicant(client)
    await _template(client, default=True)
    other = await _template(client, subject="Other {{company_name}}")
    assert (await _reject(client, app_id, template_id=other["id"])).status_code == 200
    (row,) = await _rows(db_session, app_id)
    assert row.payload["template_id"] == other["id"]
    assert row.payload["template_subject"] == "Other {{company_name}}"


@pytest.mark.usefixtures("migrated_db", "bucket", "multi_mode", "sent")
async def test_foreign_template_id_is_a_404_and_queues_nothing(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _company_with_applicant(client)
    foreign = await _template(client)
    await client.post("/api/v1/auth/logout")
    applicants, _ = await _company_with_applicants(client, 2, name_prefix="Other Co")
    ids = await _ids_by_email(client)
    a, b = (ids[app["email"]] for app in applicants)

    resp = await _reject(client, a, template_id=foreign["id"])
    assert resp.status_code == 404, resp.text
    assert (await client.get(f"/api/v1/applications/{a}")).json()["stage"] == "new"
    assert await _rows(db_session, a) == []

    resp = await client.post(
        "/api/v1/applications/bulk-reject",
        json={"application_ids": [a, b], "notify_candidates": True, "template_id": foreign["id"]},
    )
    assert resp.status_code == 404, resp.text
    assert (await client.get(f"/api/v1/applications/{b}")).json()["stage"] == "new"
    assert await _rows(db_session, b) == []


@pytest.mark.usefixtures("migrated_db", "bucket", "multi_mode")
async def test_delivery_uses_the_snapshot_after_the_template_is_deleted(
    client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    sent: list[dict[str, Any]],
) -> None:
    monkeypatch.setattr(outbox_service, "EAGER_DELIVERY_FOR_TESTS", False)
    monkeypatch.setattr(outbox_service.queue, "enqueue", _noop_enqueue)
    app_id, company_name = await _company_with_applicant(client)
    template = await _template(client, default=True)
    assert (await _reject(client, app_id)).status_code == 200
    assert (await client.delete(f"{BASE}/{template['id']}")).status_code == 204

    (row,) = await _rows(db_session, app_id)
    outbox_service.dispatch(row)
    (mail,) = sent
    assert mail["subject"] == f"Custom {company_name}"
    assert mail["body"].startswith("Hello Jane\n\nCustom body.")


async def _noop_enqueue(*args: Any, **kwargs: Any) -> None:
    return None


@pytest.mark.usefixtures("migrated_db", "bucket", "multi_mode")
async def test_preview_by_template_id_matches_the_sent_mail(
    client: AsyncClient, sent: list[dict[str, Any]]
) -> None:
    app_id, _ = await _company_with_applicant(client)
    template = await _template(client)
    resp = await client.get(
        f"/api/v1/applications/{app_id}/email-preview",
        params={"kind": "rejection", "template_id": template["id"]},
    )
    assert resp.status_code == 200, resp.text
    preview = resp.json()
    assert (await _reject(client, app_id, template_id=template["id"])).status_code == 200
    mail = sent[-1]  # the apply confirmation went out first
    assert mail["subject"] == preview["subject"]
    assert mail["body"] == preview["text"]
    assert mail["html"] == preview["html"]


@pytest.mark.usefixtures("migrated_db", "bucket", "multi_mode", "sent")
async def test_preview_builtin_keyword_and_bad_ids(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    app_id, company_name = await _company_with_applicant(client)
    await _template(client, default=True)
    url = f"/api/v1/applications/{app_id}/email-preview"
    resp = await client.get(url, params={"kind": "rejection"})
    assert resp.json()["subject"] == f"Custom {company_name}"
    resp = await client.get(url, params={"kind": "rejection", "template_id": "builtin"})
    assert resp.status_code == 200, resp.text
    assert resp.json()["subject"] == f"Your application to {company_name}"
    assert (
        await client.get(url, params={"kind": "rejection", "template_id": str(uuid4())})
    ).status_code == 404
    assert (
        await client.get(url, params={"kind": "rejection", "template_id": "nope"})
    ).status_code == 422

    assert (await _reject(client, app_id, template_id="builtin")).status_code == 200
    (row,) = await _rows(db_session, app_id)
    assert row.payload["template_id"] is None
    assert row.payload["template_subject"] == email_render.BUILTIN["rejection"].subject


@pytest.mark.usefixtures("migrated_db", "bucket", "multi_mode", "sent")
async def test_bulk_reject_and_bulk_stage_carry_the_template(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    applicants, _ = await _company_with_applicants(client, 2, name_prefix="Tpl Co")
    ids = await _ids_by_email(client)
    a, b = (ids[app["email"]] for app in applicants)
    rejection = await _template(client)
    advance = await _template(client, "stage_advance", subject="See you {{candidate_first_name}}")

    resp = await client.post(
        "/api/v1/applications/bulk-stage",
        json={
            "application_ids": [a],
            "stage": "interview",
            "notify_candidates": True,
            "template_id": advance["id"],
        },
    )
    assert resp.status_code == 200, resp.text
    (row,) = await _rows(db_session, a, "stage_advance")
    assert row.payload["template_id"] == advance["id"]

    resp = await client.post(
        "/api/v1/applications/bulk-reject",
        json={"application_ids": [a, b], "notify_candidates": True, "template_id": rejection["id"]},
    )
    assert resp.status_code == 200, resp.text
    for app_id in (a, b):
        rows = await _rows(db_session, app_id)
        assert [r.payload["template_id"] for r in rows] == [rejection["id"]]


@pytest.mark.usefixtures("migrated_db", "bucket", "multi_mode", "sent")
async def test_resolver_follows_the_default_switch_and_the_builtin_reset(
    client: AsyncClient,
) -> None:
    app_id, company_name = await _company_with_applicant(client)
    url = f"/api/v1/applications/{app_id}/email-preview"
    a = await _template(client, subject="A {{company_name}}", default=True)
    b = await _template(client, subject="B {{company_name}}")
    assert (await client.get(url, params={"kind": "rejection"})).json()[
        "subject"
    ] == f"A {company_name}"
    assert (await client.post(f"{BASE}/{b['id']}/default")).status_code == 200
    assert (await client.get(url, params={"kind": "rejection"})).json()[
        "subject"
    ] == f"B {company_name}"
    assert (
        await client.post(f"{BASE}/builtin/default", json={"kind": "rejection"})
    ).status_code == 204
    assert (await client.get(url, params={"kind": "rejection"})).json()["subject"] == (
        f"Your application to {company_name}"
    )
    assert (await client.post(f"{BASE}/{a['id']}/default")).status_code == 200
    assert (await client.delete(f"{BASE}/{a['id']}")).status_code == 204
    assert (await client.get(url, params={"kind": "rejection"})).json()["subject"] == (
        f"Your application to {company_name}"
    )
