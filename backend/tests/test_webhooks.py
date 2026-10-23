"""Outbound webhooks (card D4, part B): endpoints, signed deliveries, arq
retries, and the three emitting events."""

import hashlib
import hmac
import json
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import pytest
from arq import Retry
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import settings
from app.models import Application, ApplicationStage, Candidate, Company, Job
from app.models.quiz import AttemptStatus, QuizAttempt
from app.models.webhook import DeliveryStatus, WebhookDelivery, WebhookEndpoint
from app.services import webhooks
from tests.db import database_reachable, s3_reachable
from tests.helpers import upload_pdf

PDF_BYTES = b"%PDF-1.4 webhook flow"


# --- DB-free ---------------------------------------------------------------


def test_signature_is_hmac_sha256_over_timestamp_and_body() -> None:
    body = b'{"event":"ping"}'
    expected = hmac.new(b"whsec_x", b"1700000000." + body, hashlib.sha256).hexdigest()
    assert webhooks.sign("whsec_x", 1700000000, body) == f"sha256={expected}"


@pytest.mark.parametrize(
    "url",
    [
        "http://hooks.example.com/x",
        "https://localhost/hook",
        "https://127.0.0.1/hook",
        "https://10.1.2.3/hook",
        "https://192.168.0.9/hook",
        "https://[::1]/hook",
        "ftp://hooks.example.com/x",
        "not a url",
    ],
)
def test_validate_url_rejects_plaintext_and_private_targets(url: str) -> None:
    with pytest.raises(webhooks.InvalidUrl):
        webhooks.validate_url(url)


def test_validate_url_accepts_public_https() -> None:
    webhooks.validate_url("https://hooks.slack.com/services/T0/B0/x")


def test_application_payload_carries_summary_only() -> None:
    attempt = QuizAttempt(
        status=AttemptStatus.COMPLETED,
        score=0.5,
        completed_at=datetime(2026, 10, 2, 10, 0, tzinfo=UTC),
        integrity={"flags": [{"code": "tab_hidden", "summary": "left the tab 2x", "detail": "x"}]},
        question_ids=["q1", "q2"],
    )
    application = Application(
        id=uuid4(),
        candidate=Candidate(name="Jane", email="jane@example.com"),
        job=Job(id=uuid4(), title="Backend Engineer", slug="backend-engineer"),
        stage=ApplicationStage.NEW,
        created_at=datetime(2026, 10, 1, 9, 0, tzinfo=UTC),
        source="linkedin",
        quiz_attempts=[attempt],
    )
    data = webhooks.application_payload(application)
    assert data["candidate"] == {"name": "Jane", "email": "jane@example.com"}
    assert data["job"]["title"] == "Backend Engineer" and data["job"]["slug"] == "backend-engineer"
    assert data["stage"] == "new" and data["source"] == "linkedin"
    assert data["quiz"] == {
        "status": "completed",
        "score_percent": 50,
        "completed_at": "2026-10-02T10:00:00+00:00",
        "flags": ["left the tab 2x"],
    }
    text = json.dumps(data)
    for forbidden in ("correct_key", "question_ids", "q1", "detail", "message", "cv_object_key"):
        assert forbidden not in text


# --- DB-backed -------------------------------------------------------------

pytestmark_db = pytest.mark.skipif(
    not (database_reachable() and s3_reachable()),
    reason="database and object storage required (start postgres+minio or use CI)",
)


@pytest.fixture
def multi_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "mode", "multi")


@pytest.fixture
async def ctx() -> Any:
    engine = create_async_engine(settings.database_url, poolclass=NullPool)
    yield {"session_factory": async_sessionmaker(engine, expire_on_commit=False)}
    await engine.dispose()


async def _register(client: AsyncClient) -> tuple[str, dict[str, str]]:
    creds = {
        "email": f"admin-{uuid4().hex[:8]}@ganek-ci.dev",
        "password": "a-long-secure-password",
    }
    name = f"Hook Co {uuid4().hex[:6]}"
    resp = await client.post("/api/v1/auth/register", json={"company_name": name, **creds})
    assert resp.status_code == 201, resp.text
    return name.lower().replace(" ", "-"), creds


@pytestmark_db
@pytest.mark.usefixtures("migrated_db", "multi_mode")
async def test_admin_creates_tests_lists_and_deletes_endpoint(client: AsyncClient) -> None:
    await _register(client)
    bad = await client.post(
        "/api/v1/webhooks",
        json={"name": "Local", "url": "http://localhost:9/x", "events": ["application.created"]},
    )
    assert bad.status_code == 422
    created = await client.post(
        "/api/v1/webhooks",
        json={
            "name": "Slack",
            "url": "https://hooks.example.com/services/x",
            "events": ["application.created", "stage.changed"],
        },
    )
    assert created.status_code == 201, created.text
    hook = created.json()
    assert hook["secret"].startswith("whsec_") and len(hook["secret"]) >= 40
    assert hook["events"] == ["application.created", "stage.changed"] and hook["is_active"]

    listed = (await client.get("/api/v1/webhooks")).json()
    assert [h["id"] for h in listed] == [hook["id"]]
    assert "secret" not in listed[0] and listed[0]["last_delivery"] is None

    ping = await client.post(f"/api/v1/webhooks/{hook['id']}/test")
    assert ping.status_code == 202, ping.text
    assert ping.json()["event"] == "ping" and ping.json()["status"] == "queued"
    deliveries = (await client.get(f"/api/v1/webhooks/{hook['id']}/deliveries")).json()
    assert [d["event"] for d in deliveries] == ["ping"]
    assert (await client.get("/api/v1/webhooks")).json()[0]["last_delivery"]["status"] == "queued"

    assert (await client.delete(f"/api/v1/webhooks/{hook['id']}")).status_code == 204
    assert (await client.delete(f"/api/v1/webhooks/{hook['id']}")).status_code == 404
    assert (await client.get("/api/v1/webhooks")).json() == []
    types = [a["type"] for a in (await client.get("/api/v1/activity")).json()]
    assert types[:2] == ["webhook.deleted", "webhook.created"]


@pytestmark_db
@pytest.mark.usefixtures("migrated_db", "seeded_bank", "bucket", "multi_mode")
async def test_events_create_deliveries_for_subscribed_endpoints(client: AsyncClient) -> None:
    from sqlalchemy import update

    slug, creds = await _register(client)
    all_events = ["application.created", "stage.changed", "quiz.completed"]
    hook = (
        await client.post(
            "/api/v1/webhooks",
            json={"name": "All", "url": "https://hooks.example.com/all", "events": all_events},
        )
    ).json()
    quiet = (
        await client.post(
            "/api/v1/webhooks",
            json={
                "name": "Stages",
                "url": "https://hooks.example.com/s",
                "events": ["stage.changed"],
            },
        )
    ).json()
    job = (await client.post("/api/v1/jobs", json={"title": "Py Dev", "tags": ["python"]})).json()
    engine = create_async_engine(settings.database_url, poolclass=NullPool)
    async with async_sessionmaker(engine)() as db:
        await db.execute(
            update(Job)
            .where(Job.id == job["id"])
            .values(quiz_config={"enabled": True, "tags": ["python"], "question_count": 2})
        )
        await db.commit()
    await engine.dispose()
    assert (await client.post(f"/api/v1/jobs/{job['id']}/publish")).status_code == 200
    await client.post("/api/v1/auth/logout")

    base = f"/api/v1/public/companies/{slug}/jobs/{job['slug']}"
    ticket = (await client.post(f"{base}/apply/upload-url")).json()
    assert (await upload_pdf(ticket, PDF_BYTES)).is_success
    email = f"jane-{uuid4().hex[:8]}@ganek-ci.dev"
    applied = await client.post(
        f"{base}/apply",
        json={
            "name": "Jane",
            "email": email,
            "cv_object_key": ticket["object_key"],
            "cv_filename": "cv.pdf",
        },
    )
    token = applied.json()["quiz_token"]
    while True:
        body = (await client.post(f"/api/v1/public/quiz/{token}/next")).json()
        if body["done"]:
            break
        question = body["question"]
        await client.post(
            f"/api/v1/public/quiz/{token}/answer",
            json={"question_id": question["id"], "answer_key": question["options"][0]["key"]},
        )

    assert (await client.post("/api/v1/auth/login", json=creds)).status_code == 200
    app_id = (await client.get("/api/v1/applications")).json()["items"][0]["id"]
    assert (
        await client.patch(f"/api/v1/applications/{app_id}/stage", json={"stage": "screening"})
    ).status_code == 200

    deliveries = (await client.get(f"/api/v1/webhooks/{hook['id']}/deliveries")).json()
    assert [d["event"] for d in deliveries] == [
        "stage.changed",
        "quiz.completed",
        "application.created",
    ]
    assert all(d["status"] == "queued" and d["attempts"] == 0 for d in deliveries)
    quiet_deliveries = (await client.get(f"/api/v1/webhooks/{quiet['id']}/deliveries")).json()
    assert [d["event"] for d in quiet_deliveries] == ["stage.changed"]

    # the stored payloads: summary data only, never quiz internals
    engine = create_async_engine(settings.database_url, poolclass=NullPool)
    async with async_sessionmaker(engine)() as db:
        rows = (
            (
                await db.execute(
                    select(WebhookDelivery).where(WebhookDelivery.endpoint_id == hook["id"])
                )
            )
            .scalars()
            .all()
        )
    await engine.dispose()
    by_event = {row.event: row.payload for row in rows}
    assert by_event["application.created"]["data"]["candidate"]["email"] == email
    assert by_event["stage.changed"]["data"]["stage"] == "screening"
    assert by_event["stage.changed"]["data"]["previous_stage"] == "new"
    assert by_event["quiz.completed"]["data"]["quiz"]["status"] == "completed"
    assert "correct_key" not in json.dumps(by_event) and "question_ids" not in json.dumps(by_event)


async def _endpoint_with_delivery(db: AsyncSession) -> tuple[WebhookEndpoint, WebhookDelivery, str]:
    company = Company(slug=f"wh-{uuid4().hex[:8]}", name="Hook Co", settings={})
    db.add(company)
    await db.flush()
    endpoint, secret = webhooks.new_endpoint(
        company, name="Slack", url="https://hooks.example.com/x", events=["ping"]
    )
    db.add(endpoint)
    await db.flush()
    delivery = WebhookDelivery(
        company_id=company.id,
        endpoint_id=endpoint.id,
        event="ping",
        payload={"event": "ping", "data": {"hello": "world"}},
    )
    db.add(delivery)
    await db.commit()
    await db.refresh(delivery)
    return endpoint, delivery, secret


@pytestmark_db
@pytest.mark.usefixtures("migrated_db")
async def test_deliver_posts_signed_body_and_marks_delivered(
    db_session: AsyncSession, ctx: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.worker import deliver_webhook

    endpoint, delivery, secret = await _endpoint_with_delivery(db_session)
    seen: list[tuple[str, bytes, dict[str, str]]] = []

    def fake_post(url: str, body: bytes, headers: dict[str, str]) -> int:
        seen.append((url, body, headers))
        return 200

    monkeypatch.setattr(webhooks, "_http_post", fake_post)
    await deliver_webhook(ctx, str(delivery.id))

    assert len(seen) == 1
    url, body, headers = seen[0]
    assert url == "https://hooks.example.com/x"
    assert headers["X-Ganek-Event"] == "ping" and headers["X-Ganek-Delivery"] == str(delivery.id)
    assert headers["Content-Type"] == "application/json"
    expected = webhooks.sign(secret, int(headers["X-Ganek-Timestamp"]), body)
    assert headers["X-Ganek-Signature"] == expected
    assert json.loads(body)["data"] == {"hello": "world"}
    assert json.loads(body)["id"] == str(delivery.id)

    await db_session.refresh(delivery)
    assert delivery.status is DeliveryStatus.DELIVERED
    assert delivery.attempts == 1 and delivery.response_status == 200
    assert delivery.delivered_at is not None

    # a second run is a no-op (status check), never a duplicate POST
    await deliver_webhook(ctx, str(delivery.id))
    assert len(seen) == 1


@pytestmark_db
@pytest.mark.usefixtures("migrated_db")
async def test_deliver_retries_with_backoff_then_parks_failed(
    db_session: AsyncSession, ctx: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.worker import deliver_webhook

    _endpoint, delivery, _secret = await _endpoint_with_delivery(db_session)

    def exploding(url: str, body: bytes, headers: dict[str, str]) -> int:
        raise webhooks.DeliveryError("HTTP 503")

    monkeypatch.setattr(webhooks, "_http_post", exploding)
    for attempt in range(1, webhooks.MAX_ATTEMPTS):
        with pytest.raises(Retry) as info:
            await deliver_webhook(ctx, str(delivery.id))
        expected_delay = webhooks.RETRY_DELAYS_SECONDS[
            min(attempt - 1, len(webhooks.RETRY_DELAYS_SECONDS) - 1)
        ]
        assert info.value.defer_score == expected_delay * 1000
        await db_session.refresh(delivery)
        assert delivery.status is DeliveryStatus.QUEUED and delivery.attempts == attempt
        assert delivery.last_error == "HTTP 503"

    await deliver_webhook(ctx, str(delivery.id))  # last allowed attempt: no Retry
    await db_session.refresh(delivery)
    assert delivery.status is DeliveryStatus.FAILED
    assert delivery.attempts == webhooks.MAX_ATTEMPTS
