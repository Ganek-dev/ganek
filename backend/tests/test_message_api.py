"""One-off message to a candidate (card "Candidate emails", PR 4): POST
/applications/{id}/message queues kind "message" with Reply-To set to the
recruiter, records email.message, and the preview equals the sent mail."""

from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models import EmailOutbox
from app.services import email as email_service
from tests.db import database_reachable, s3_reachable
from tests.test_email_preview_api import _company_with_applicant
from tests.test_email_templates_api import _member_login, _register_admin

pytestmark = pytest.mark.skipif(
    not (database_reachable() and s3_reachable()),
    reason="database and object storage required (start postgres+minio or use CI)",
)

MESSAGE = {"subject": "Quick question", "body": "Hi Jane,\n\nPortfolio?"}


@pytest.fixture
def multi_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "mode", "multi")


@pytest.fixture
def sent(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """Every mail handed to the transport, as send_email kwargs. Records the
    rendering like the real send_email so dispatch stores it on the row."""
    captured: list[dict[str, Any]] = []

    def capture(**kw: Any) -> None:
        email_service.last_rendered.set((kw["subject"], kw["body"]))
        captured.append(kw)

    monkeypatch.setattr(email_service, "send_email", capture)
    return captured


async def _message(client: AsyncClient, app_id: str, **extra: Any) -> Any:
    return await client.post(f"/api/v1/applications/{app_id}/message", json={**MESSAGE, **extra})


async def _message_rows(db: AsyncSession, app_id: str) -> list[EmailOutbox]:
    result = await db.execute(
        select(EmailOutbox).where(
            EmailOutbox.application_id == app_id, EmailOutbox.kind == "message"
        )
    )
    return list(result.scalars().all())


async def _me(client: AsyncClient) -> str:
    return str((await client.get("/api/v1/auth/me")).json()["email"])


async def _timeline(client: AsyncClient, app_id: str) -> list[dict[str, Any]]:
    resp = await client.get(f"/api/v1/applications/{app_id}/timeline")
    assert resp.status_code == 200, resp.text
    rows: list[dict[str, Any]] = resp.json()
    return rows


@pytest.mark.usefixtures("migrated_db", "bucket", "multi_mode")
async def test_message_queues_with_reply_to_and_records_the_activity(
    client: AsyncClient, db_session: AsyncSession, sent: list[dict[str, Any]]
) -> None:
    app_id, _ = await _company_with_applicant(client)
    admin_email = await _me(client)
    sent.clear()
    resp = await _message(client, app_id)
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"queued": True}

    (row,) = await _message_rows(db_session, app_id)
    assert row.payload["reply_to"] == admin_email
    assert row.payload["subject"] == "Quick question"
    (mail,) = sent
    assert mail["reply_to"] == admin_email
    assert mail["subject"] == "Quick question"
    assert mail["body"].startswith("Hi Jane,\n\nPortfolio?\n\n- ")

    rows = await _timeline(client, app_id)
    activity = next(r for r in rows if r["kind"] == "email.message")
    assert activity["actor_email"] == admin_email
    assert activity["payload"]["subject"] == "Quick question"
    email = next(r for r in rows if r["kind"] == "email" and r["payload"]["template"] == "message")
    assert email["payload"]["subject"] == "Quick question"
    assert str(email["payload"]["text"]).startswith("Hi Jane,")


@pytest.mark.usefixtures("migrated_db", "bucket", "multi_mode")
async def test_message_preview_matches_the_sent_mail(
    client: AsyncClient, sent: list[dict[str, Any]]
) -> None:
    app_id, _ = await _company_with_applicant(client)
    sent.clear()
    resp = await client.post(f"/api/v1/applications/{app_id}/message/preview", json=MESSAGE)
    assert resp.status_code == 200, resp.text
    preview = resp.json()
    assert preview["kind"] == "message"
    assert preview["body"] == MESSAGE["body"]
    assert sent == []  # a preview queues nothing

    assert (await _message(client, app_id)).status_code == 200
    (mail,) = sent
    assert mail["subject"] == preview["subject"]
    assert mail["body"] == preview["text"]
    assert mail["html"] == preview["html"]


@pytest.mark.usefixtures("migrated_db", "bucket", "multi_mode")
async def test_message_escapes_html_and_keeps_text_verbatim(
    client: AsyncClient, sent: list[dict[str, Any]]
) -> None:
    app_id, _ = await _company_with_applicant(client)
    sent.clear()
    body = "Tom & Jerry <script>alert(1)</script>"
    assert (await _message(client, app_id, body=body)).status_code == 200
    (mail,) = sent
    assert body in mail["body"]
    assert "Tom &amp; Jerry &lt;script&gt;" in mail["html"]
    assert "<script>" not in mail["html"]


@pytest.mark.usefixtures("migrated_db", "bucket", "multi_mode", "sent")
async def test_message_validation(client: AsyncClient, db_session: AsyncSession) -> None:
    app_id, _ = await _company_with_applicant(client)
    cases = [
        ({"subject": "   "}, "Subject is required"),
        ({"subject": "a\nb"}, "Subject must be one line"),
        ({"body": ""}, "Body is required"),
        ({"subject": "s" * 201}, "at most 200"),
    ]
    for extra, detail in cases:
        resp = await _message(client, app_id, **extra)
        assert resp.status_code == 422, resp.text
        assert detail in resp.text, (extra, resp.text)
    assert await _message_rows(db_session, app_id) == []


@pytest.mark.usefixtures("migrated_db", "bucket", "multi_mode")
async def test_message_is_for_any_member_but_not_api_keys(
    client: AsyncClient, sent: list[dict[str, Any]]
) -> None:
    app_id, _ = await _company_with_applicant(client)
    key = (await client.post("/api/v1/api-keys", json={"name": "Zap", "scope": "write"})).json()
    await _member_login(client)
    member_email = await _me(client)
    sent.clear()
    assert (await _message(client, app_id)).status_code == 200
    assert sent[0]["reply_to"] == member_email

    await client.post("/api/v1/auth/logout")
    resp = await client.post(
        f"/api/v1/applications/{app_id}/message",
        json=MESSAGE,
        headers={"Authorization": f"Bearer {key['secret']}"},
    )
    assert resp.status_code == 401, resp.text
    assert len(sent) == 1


@pytest.mark.usefixtures("migrated_db", "bucket", "multi_mode", "sent")
async def test_message_is_tenant_scoped(client: AsyncClient, db_session: AsyncSession) -> None:
    app_id, _ = await _company_with_applicant(client)
    await client.post("/api/v1/auth/logout")
    await _register_admin(client)  # another workspace, logged in as its admin
    assert (await _message(client, app_id)).status_code == 404
    assert await _message_rows(db_session, app_id) == []


@pytest.mark.usefixtures("migrated_db", "bucket", "multi_mode", "sent")
async def test_message_on_a_demo_instance_records_the_activity_only(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    app_id, _ = await _company_with_applicant(client)
    monkeypatch.setattr(settings, "demo_mode", True)
    resp = await _message(client, app_id)
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"queued": False}
    assert await _message_rows(db_session, app_id) == []
    rows = await _timeline(client, app_id)
    assert any(r["kind"] == "email.message" for r in rows)
