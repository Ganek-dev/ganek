"""One-off edit of a single stage send (card "Candidate emails", PR 4):
PATCH stage takes a literal subject and body for this send only, rendered
inside the kind's fixed action block and footer; bulk routes never do."""

from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.services import email as email_service
from app.services import email_render
from tests.db import database_reachable, s3_reachable
from tests.test_bulk_reject import _company_with_applicants, _ids_by_email
from tests.test_email_preview_api import _company_with_applicant
from tests.test_email_templates_delivery import BASE, _reject, _rows, _template

pytestmark = pytest.mark.skipif(
    not (database_reachable() and s3_reachable()),
    reason="database and object storage required (start postgres+minio or use CI)",
)


@pytest.fixture
def multi_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "mode", "multi")


@pytest.fixture
def sent(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """Every mail the senders hand to the transport, as send_email kwargs."""
    captured: list[dict[str, Any]] = []
    monkeypatch.setattr(email_service, "send_email", lambda **kw: captured.append(kw))
    return captured


OVERRIDE = {"subject": "A personal note", "body": "Dear Jane\n\nThank you for the conversation."}


async def _stage(client: AsyncClient, app_id: str, **extra: Any) -> Any:
    return await client.patch(f"/api/v1/applications/{app_id}/stage", json=extra)


@pytest.mark.usefixtures("migrated_db", "bucket", "multi_mode")
async def test_override_is_delivered_verbatim_inside_the_fixed_block(
    client: AsyncClient, db_session: AsyncSession, sent: list[dict[str, Any]]
) -> None:
    app_id, _ = await _company_with_applicant(client)
    sent.clear()
    assert (await _reject(client, app_id, **OVERRIDE)).status_code == 200
    (row,) = await _rows(db_session, app_id)
    assert row.payload["override_subject"] == "A personal note"
    assert row.payload["override_body"] == OVERRIDE["body"]
    assert row.payload["template_subject"] == email_render.BUILTIN["rejection"].subject
    (mail,) = sent
    assert mail["subject"] == "A personal note"
    assert mail["body"].startswith(
        "Dear Jane\n\nThank you for the conversation.\n\nSee open positions:"
    )
    assert "Privacy & your data:" in mail["body"]


@pytest.mark.usefixtures("migrated_db", "bucket", "multi_mode")
async def test_override_braces_stay_literal(
    client: AsyncClient, sent: list[dict[str, Any]]
) -> None:
    app_id, _ = await _company_with_applicant(client)
    sent.clear()
    resp = await _reject(
        client,
        app_id,
        subject="Hi {{candidate_name}}",
        body="{{salary}} is not a placeholder here",
    )
    assert resp.status_code == 200, resp.text
    (mail,) = sent
    assert mail["subject"] == "Hi {{candidate_name}}"
    assert "{{salary}} is not a placeholder here" in mail["body"]


@pytest.mark.usefixtures("migrated_db", "bucket", "multi_mode", "sent")
async def test_override_validation(client: AsyncClient, db_session: AsyncSession) -> None:
    app_id, _ = await _company_with_applicant(client)
    cases = [
        ({"subject": "Only a subject"}, "Subject and body go together"),
        ({"subject": "a\nb", "body": "x"}, "Subject must be one line"),
        ({"subject": "   ", "body": "x"}, "Subject and body go together"),
        ({"subject": "s" * 201, "body": "x"}, "at most 200"),
    ]
    for extra, detail in cases:
        resp = await _reject(client, app_id, **extra)
        assert resp.status_code == 422, resp.text
        assert detail in resp.text, (extra, resp.text)
    assert await _rows(db_session, app_id) == []
    app = (await client.get(f"/api/v1/applications/{app_id}")).json()
    assert app["stage"] == "new"


@pytest.mark.usefixtures("migrated_db", "bucket", "multi_mode")
async def test_override_does_not_touch_the_template(
    client: AsyncClient, db_session: AsyncSession, sent: list[dict[str, Any]]
) -> None:
    app_id, _ = await _company_with_applicant(client)
    template = await _template(client, default=True)
    assert (await _reject(client, app_id, **OVERRIDE)).status_code == 200
    kinds = (await client.get(BASE)).json()["kinds"]
    rejection = next(k for k in kinds if k["kind"] == "rejection")
    (stored,) = rejection["templates"]
    assert stored["subject"] == template["subject"] and stored["body"] == template["body"]
    (row,) = await _rows(db_session, app_id)
    assert row.payload["template_id"] == template["id"]
    assert sent[-1]["subject"] == "A personal note"


@pytest.mark.usefixtures("migrated_db", "bucket", "multi_mode")
async def test_bulk_routes_ignore_one_off_overrides(
    client: AsyncClient, db_session: AsyncSession, sent: list[dict[str, Any]]
) -> None:
    applicants, _ = await _company_with_applicants(client, 3, name_prefix="Edit Co")
    ids = await _ids_by_email(client)
    a, b, c = (ids[app["email"]] for app in applicants)
    sent.clear()

    resp = await client.post(
        "/api/v1/applications/bulk-stage",
        json={"application_ids": [a], "stage": "interview", "notify_candidates": True, **OVERRIDE},
    )
    assert resp.status_code == 200, resp.text
    (row,) = await _rows(db_session, a, "stage_advance")
    assert "override_subject" not in row.payload

    resp = await client.post(
        "/api/v1/applications/bulk-reject",
        json={"application_ids": [b, c], "notify_candidates": True, **OVERRIDE},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["rejected"] == 2
    for app_id in (b, c):
        (row,) = await _rows(db_session, app_id)
        assert "override_subject" not in row.payload
    assert len(sent) == 3
    assert all(
        mail["subject"].startswith(
            ("Next step: interviews at Edit Co", "Your application to Edit Co")
        )
        for mail in sent
    ), [mail["subject"] for mail in sent]


@pytest.mark.usefixtures("migrated_db", "bucket", "multi_mode")
async def test_interview_override_keeps_the_status_link_and_signoff(
    client: AsyncClient, sent: list[dict[str, Any]]
) -> None:
    app_id, company_name = await _company_with_applicant(client)
    sent.clear()
    resp = await _stage(
        client,
        app_id,
        stage="interview",
        notify_candidate=True,
        subject="Let's talk next week",
        body="Hi Jane\n\nWe would like to meet you.",
    )
    assert resp.status_code == 200, resp.text
    (mail,) = sent
    assert mail["subject"] == "Let's talk next week"
    assert mail["body"].startswith(
        "Hi Jane\n\nWe would like to meet you.\n\nTrack your application:"
    )
    assert f"Looking forward to it,\nThe {company_name} hiring team" in mail["body"]
