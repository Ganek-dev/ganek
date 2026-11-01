"""Delayed rejection mail: send_after on the stage, bulk-reject and
bulk-stage routes holds the mail as a scheduled outbox row; bad values are a
422 with nothing moved."""

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import settings
from app.models import Application, EmailOutbox, EmailStatus
from app.services import email as email_service
from app.services import outbox as outbox_service
from app.services import scheduled_emails
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


async def _schedule(client: AsyncClient, app_id: str) -> dict[str, Any]:
    resp = await client.patch(
        f"/api/v1/applications/{app_id}/stage",
        json={"stage": "rejected", "notify_candidate": True, "send_after": _when(days=1)},
    )
    assert resp.status_code == 200, resp.text
    (row,) = await _emails(client, app_id)
    assert row["status"] == "scheduled"
    return row


def _cancel_url(app_id: str, email_id: str) -> str:
    return f"/api/v1/applications/{app_id}/emails/{email_id}/cancel"


@pytest.mark.usefixtures("migrated_db", "bucket", "multi_mode")
async def test_staff_cancels_a_scheduled_mail(
    client: AsyncClient, sent: list[dict[str, Any]]
) -> None:
    applicants, creds = await _company_with_applicants(client, 1)
    app_id = (await _ids_by_email(client))[applicants[0]["email"]]
    row = await _schedule(client, app_id)

    resp = await client.post(_cancel_url(app_id, row["id"]))
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "cancelled"
    assert resp.json()["cancelled_at"] is not None
    # a second cancel finds nothing scheduled
    again = await client.post(_cancel_url(app_id, row["id"]))
    assert again.status_code == 409
    assert again.json() == {"detail": "This email is not scheduled"}

    activity = (await client.get("/api/v1/activity")).json()
    feed = [a for a in activity if a["type"] == "email.cancelled"]
    assert len(feed) == 1
    assert feed[0]["actor_email"] == creds["email"]
    assert feed[0]["payload"] == {"email_id": row["id"], "kind": "rejection"}
    assert sent == []
    assert (await _emails(client, app_id))[0]["status"] == "cancelled"
    # an unknown email id on a real application
    assert (await client.post(_cancel_url(app_id, str(uuid4())))).status_code == 404


@pytest.mark.usefixtures("migrated_db", "bucket", "multi_mode")
async def test_cancel_is_tenant_scoped_and_session_only(client: AsyncClient) -> None:
    applicants, _ = await _company_with_applicants(client, 1)
    app_id = (await _ids_by_email(client))[applicants[0]["email"]]
    row = await _schedule(client, app_id)
    key = (await client.post("/api/v1/api-keys", json={"name": "Zap", "scope": "read"})).json()
    bearer = {"Authorization": f"Bearer {key['secret']}"}

    await client.post("/api/v1/auth/logout")
    other = {
        "email": f"other-{uuid4().hex[:8]}@ganek-ci.dev",
        "password": "a-long-secure-password",
    }
    reg = await client.post(
        "/api/v1/auth/register", json={"company_name": f"Other {uuid4().hex[:6]}", **other}
    )
    assert reg.status_code == 201, reg.text
    assert (await client.post(_cancel_url(app_id, row["id"]))).status_code == 404

    await client.post("/api/v1/auth/logout")
    resp = await client.post(_cancel_url(app_id, row["id"]), headers=bearer)
    assert resp.status_code == 401


@pytest.mark.usefixtures("migrated_db", "bucket", "multi_mode")
async def test_unreject_cancels_the_scheduled_mail(
    client: AsyncClient, sent: list[dict[str, Any]]
) -> None:
    applicants, creds = await _company_with_applicants(client, 2)
    ids = await _ids_by_email(client)
    a, b = (ids[app["email"]] for app in applicants)
    scheduled = await _schedule(client, a)

    # b was rejected with an immediate mail: it is already sent
    resp = await client.patch(
        f"/api/v1/applications/{b}/stage", json={"stage": "rejected", "notify_candidate": True}
    )
    assert resp.status_code == 200, resp.text
    assert len(sent) == 1

    # the undo toast's call: stage back, notify false
    for app_id in (a, b):
        resp = await client.patch(
            f"/api/v1/applications/{app_id}/stage",
            json={"stage": "screening", "notify_candidate": False},
        )
        assert resp.status_code == 200, resp.text

    (row,) = await _emails(client, a)
    assert (row["id"], row["status"]) == (scheduled["id"], "cancelled")
    assert [r["status"] for r in await _emails(client, b)] == ["sent"]
    cancelled = [
        x for x in (await client.get("/api/v1/activity")).json() if x["type"] == "email.cancelled"
    ]
    assert len(cancelled) == 1
    assert cancelled[0]["actor_email"] == creds["email"]
    assert len(sent) == 1


@pytest.mark.usefixtures("migrated_db", "bucket", "multi_mode")
async def test_unreject_cancels_before_queueing_the_new_stage_mail(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch, sent: list[dict[str, Any]]
) -> None:
    applicants, _ = await _company_with_applicants(client, 1)
    app_id = (await _ids_by_email(client))[applicants[0]["email"]]
    await _schedule(client, app_id)
    monkeypatch.setattr(email_service, "send_stage_advance", lambda **kw: None)
    calls: list[str] = []
    real_cancel = scheduled_emails.cancel_for_application
    real_queue = outbox_service.queue_email

    async def spy_cancel(*args: Any, **kw: Any) -> int:
        calls.append("cancel")
        return await real_cancel(*args, **kw)

    async def spy_queue(*args: Any, **kw: Any) -> Any:
        calls.append("queue")
        return await real_queue(*args, **kw)

    monkeypatch.setattr(scheduled_emails, "cancel_for_application", spy_cancel)
    monkeypatch.setattr(outbox_service, "queue_email", spy_queue)
    resp = await client.patch(
        f"/api/v1/applications/{app_id}/stage",
        json={"stage": "interview", "notify_candidate": True},
    )
    assert resp.status_code == 200, resp.text
    assert calls == ["cancel", "queue"]
    assert [r["status"] for r in await _emails(client, app_id)] == ["cancelled"]


@pytest.mark.usefixtures("migrated_db", "bucket", "multi_mode")
async def test_bulk_stage_out_of_rejected_cancels(client: AsyncClient) -> None:
    applicants, creds = await _company_with_applicants(client, 1)
    app_id = (await _ids_by_email(client))[applicants[0]["email"]]
    await _schedule(client, app_id)

    resp = await client.post(
        "/api/v1/applications/bulk-stage",
        json={"application_ids": [app_id], "stage": "screening"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"updated": 1, "skipped": 0}
    assert [r["status"] for r in await _emails(client, app_id)] == ["cancelled"]
    (cancelled,) = [
        x for x in (await client.get("/api/v1/activity")).json() if x["type"] == "email.cancelled"
    ]
    assert cancelled["actor_email"] == creds["email"]


@pytest.mark.usefixtures("migrated_db", "bucket", "multi_mode")
async def test_cancel_route_on_a_sent_row_is_409_and_leaves_it(
    client: AsyncClient, sent: list[dict[str, Any]]
) -> None:
    applicants, _ = await _company_with_applicants(client, 1)
    app_id = (await _ids_by_email(client))[applicants[0]["email"]]
    resp = await client.patch(
        f"/api/v1/applications/{app_id}/stage",
        json={"stage": "rejected", "notify_candidate": True},
    )
    assert resp.status_code == 200, resp.text
    (before,) = await _emails(client, app_id)
    assert before["status"] == "sent"

    resp = await client.post(_cancel_url(app_id, before["id"]))
    assert resp.status_code == 409
    assert resp.json() == {"detail": "This email is not scheduled"}
    assert await _emails(client, app_id) == [before]


@pytest.mark.usefixtures("migrated_db", "bucket", "multi_mode")
async def test_member_can_cancel_and_reviewer_cannot(client: AsyncClient) -> None:
    applicants, admin = await _company_with_applicants(client, 2)
    ids = await _ids_by_email(client)
    a, b = (ids[app["email"]] for app in applicants)
    row_a = await _schedule(client, a)
    row_b = await _schedule(client, b)

    pw = "member-password-1234"
    users = {}
    for role in ("member", "reviewer"):
        email = f"{role}-{uuid4().hex[:8]}@ganek-ci.dev"
        body = {"email": email, "password": pw, "role": role}
        resp = await client.post("/api/v1/users", json=body)
        assert resp.status_code == 201, resp.text
        users[role] = email

    await client.post("/api/v1/auth/logout")
    login = {"email": users["reviewer"], "password": pw}
    assert (await client.post("/api/v1/auth/login", json=login)).status_code == 200
    assert (await client.post(_cancel_url(b, row_b["id"]))).status_code == 403

    await client.post("/api/v1/auth/logout")
    login = {"email": users["member"], "password": pw}
    assert (await client.post("/api/v1/auth/login", json=login)).status_code == 200
    resp = await client.post(_cancel_url(a, row_a["id"]))
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "cancelled"


async def _decided_at(app_id: str) -> datetime | None:
    engine = create_async_engine(settings.database_url, poolclass=NullPool)
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as db:
            row = (
                await db.execute(select(Application).where(Application.id == UUID(app_id)))
            ).scalar_one()
            return row.decided_at
    finally:
        await engine.dispose()


@pytest.mark.usefixtures("migrated_db", "bucket", "multi_mode")
async def test_rejected_row_can_be_mailed_again_without_a_stage_change(
    client: AsyncClient, sent: list[dict[str, Any]]
) -> None:
    applicants, _ = await _company_with_applicants(client, 1)
    app_id = (await _ids_by_email(client))[applicants[0]["email"]]
    endpoint = (
        await client.post(
            "/api/v1/webhooks",
            json={
                "name": "Zap",
                "url": "https://hooks.example.com/zap",
                "events": ["stage.changed"],
            },
        )
    ).json()
    url = f"/api/v1/applications/{app_id}/stage"

    # rejected silently: no mail yet
    resp = await client.patch(url, json={"stage": "rejected", "notify_candidate": False})
    assert resp.status_code == 200, resp.text
    assert await _emails(client, app_id) == []
    decided = await _decided_at(app_id)
    assert decided is not None
    deliveries = (await client.get(f"/api/v1/webhooks/{endpoint['id']}/deliveries")).json()

    when = _when(days=1)
    again = await client.patch(
        url, json={"stage": "rejected", "notify_candidate": True, "send_after": when}
    )
    assert again.status_code == 200, again.text
    assert again.json()["stage"] == "rejected"
    assert sent == []
    (row,) = await _emails(client, app_id)
    assert row["status"] == "scheduled"
    assert datetime.fromisoformat(row["send_after"]) == datetime.fromisoformat(when)

    changed = [
        a for a in (await client.get("/api/v1/activity")).json() if a["type"] == "stage.changed"
    ]
    assert len([a for a in changed if a["application_id"] == app_id]) == 1
    assert await _decided_at(app_id) == decided
    after = (await client.get(f"/api/v1/webhooks/{endpoint['id']}/deliveries")).json()
    assert len(after) == len(deliveries) == 1


@pytest.mark.usefixtures("migrated_db", "bucket", "multi_mode")
async def test_mail_again_refuses_a_reason_and_stays_a_noop_without_notify(
    client: AsyncClient, sent: list[dict[str, Any]]
) -> None:
    applicants, _ = await _company_with_applicants(client, 1)
    app_id = (await _ids_by_email(client))[applicants[0]["email"]]
    url = f"/api/v1/applications/{app_id}/stage"
    await client.patch(url, json={"stage": "rejected", "notify_candidate": False})

    resp = await client.patch(
        url,
        json={
            "stage": "rejected",
            "notify_candidate": True,
            "send_after": _when(days=1),
            "rejection_reason": "skills_gap",
        },
    )
    assert resp.status_code == 422
    assert resp.json() == {"detail": "A reason or note cannot change with the email"}

    resp = await client.patch(url, json={"stage": "rejected", "notify_candidate": False})
    assert resp.status_code == 200, resp.text
    assert await _emails(client, app_id) == []
    assert sent == []


@pytest.mark.usefixtures("migrated_db", "bucket", "multi_mode")
async def test_mail_again_twice_is_409_and_keeps_one_scheduled_row(
    client: AsyncClient,
) -> None:
    applicants, _ = await _company_with_applicants(client, 1)
    app_id = (await _ids_by_email(client))[applicants[0]["email"]]
    url = f"/api/v1/applications/{app_id}/stage"
    await client.patch(url, json={"stage": "rejected", "notify_candidate": False})
    body = {"stage": "rejected", "notify_candidate": True, "send_after": _when(days=1)}

    assert (await client.patch(url, json=body)).status_code == 200
    second = await client.patch(url, json=body)
    assert second.status_code == 409
    assert second.json() == {"detail": "A rejection email is already scheduled"}
    assert [r["status"] for r in await _emails(client, app_id)] == ["scheduled"]


async def _set_row_status(email_id: str, status: EmailStatus) -> None:
    engine = create_async_engine(settings.database_url, poolclass=NullPool)
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as db:
            await db.execute(
                update(EmailOutbox).where(EmailOutbox.id == UUID(email_id)).values(status=status)
            )
            await db.commit()
    finally:
        await engine.dispose()


@pytest.mark.usefixtures("migrated_db", "bucket", "multi_mode")
@pytest.mark.parametrize("status", [EmailStatus.QUEUED, EmailStatus.SENT])
async def test_mail_again_is_409_when_a_rejection_is_queued_or_sent(
    client: AsyncClient, sent: list[dict[str, Any]], status: EmailStatus
) -> None:
    applicants, _ = await _company_with_applicants(client, 1)
    app_id = (await _ids_by_email(client))[applicants[0]["email"]]
    row = await _schedule(client, app_id)
    await _set_row_status(row["id"], status)

    resp = await client.patch(
        f"/api/v1/applications/{app_id}/stage",
        json={"stage": "rejected", "notify_candidate": True},
    )
    assert resp.status_code == 409
    assert resp.json() == {"detail": "A rejection email was already sent"}
    assert sent == []
    assert len(await _emails(client, app_id)) == 1


@pytest.mark.usefixtures("migrated_db", "bucket", "multi_mode")
@pytest.mark.parametrize(
    "status",
    [
        EmailStatus.CANCELLED,
        EmailStatus.FAILED,
        EmailStatus.SUPPRESSED,
        EmailStatus.BOUNCED,
        EmailStatus.COMPLAINED,
    ],
)
async def test_mail_again_is_allowed_after_an_undelivered_rejection(
    client: AsyncClient, sent: list[dict[str, Any]], status: EmailStatus
) -> None:
    applicants, _ = await _company_with_applicants(client, 1)
    app_id = (await _ids_by_email(client))[applicants[0]["email"]]
    row = await _schedule(client, app_id)
    await _set_row_status(row["id"], status)

    resp = await client.patch(
        f"/api/v1/applications/{app_id}/stage",
        json={"stage": "rejected", "notify_candidate": True},
    )
    assert resp.status_code == 200, resp.text
    assert len(sent) == 1
    assert len(await _emails(client, app_id)) == 2


@pytest.mark.usefixtures("migrated_db", "bucket", "multi_mode")
async def test_corrected_address_reaches_only_this_candidates_scheduled_mail(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch, sent: list[dict[str, Any]]
) -> None:
    from app.worker import deliver_email

    applicants, _ = await _company_with_applicants(client, 2)
    ids = await _ids_by_email(client)
    a, b = (ids[app["email"]] for app in applicants)
    row_a = await _schedule(client, a)
    row_b = await _schedule(client, b)
    new_address = f"fixed-{uuid4().hex[:8]}@ganek-ci.dev"

    resp = await client.patch(
        f"/api/v1/applications/{a}/candidate-email", json={"email": new_address}
    )
    assert resp.status_code == 200, resp.text

    monkeypatch.setattr(settings, "smtp_host", "mail.example.com")
    engine = create_async_engine(settings.database_url, poolclass=NullPool)
    try:
        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with factory() as db:
            await db.execute(
                update(EmailOutbox)
                .where(EmailOutbox.id.in_([UUID(row_a["id"]), UUID(row_b["id"])]))
                .values(send_after=datetime.now(UTC) - timedelta(minutes=1))
            )
            await db.commit()
        await deliver_email({"session_factory": factory}, row_a["id"])
        await deliver_email({"session_factory": factory}, row_b["id"])
    finally:
        await engine.dispose()
    assert [kw["to"] for kw in sent] == [new_address, applicants[1]["email"]]
