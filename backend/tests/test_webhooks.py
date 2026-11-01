"""Outbound webhooks (card D4, part B): endpoints, signed deliveries, arq
retries, and the three emitting events."""

import hashlib
import hmac
import json
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from arq import Retry
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import settings
from app.models import Application, ApplicationStage, Candidate, Company, Job, JobStatus
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


def sample_company() -> Company:
    return Company(id=uuid4(), slug="acme", name="Acme", settings={})


def payload_application(*, attempts: list[QuizAttempt] | None = None) -> Application:
    """Fully loaded in-memory application with every sensitive field set,
    shared by the leak test and the sample shape comparison."""
    if attempts is None:
        attempts = [
            QuizAttempt(
                status=AttemptStatus.COMPLETED,
                score=0.5,
                completed_at=datetime(2026, 10, 2, 10, 0, tzinfo=UTC),
                integrity={
                    "flags": [
                        {
                            "code": "tab_hidden",
                            "summary": "left the tab 2x",
                            "detail": "raw-detail-text",
                        }
                    ]
                },
                question_ids=["q1", "q2"],
            )
        ]
    return Application(
        id=uuid4(),
        candidate=Candidate(
            name="Jane Q. Applicant",
            email="jane@example.com",
            links={"github": "https://github.com/jane"},
        ),
        job=Job(id=uuid4(), title="Backend Engineer", slug="backend-engineer"),
        stage=ApplicationStage.NEW,
        created_at=datetime(2026, 10, 1, 9, 0, tzinfo=UTC),
        source="linkedin",
        message="Hi, I shipped two Next.js apps",
        rejection_note="internal note",
        screening_answers=[{"question_id": "sq_1", "answer": "no", "match": False}],
        quiz_attempts=attempts,
        cv_object_key="cvs/x/y.pdf",
        cv_filename="jane-cv.pdf",
        cv_size=184233,
    )


def test_application_payload_carries_summary_only() -> None:
    application = payload_application()
    data = webhooks.application_payload(application, sample_company())
    assert data["candidate"] == {
        "name": "Jane Q. Applicant",
        "first_name": "Jane Q.",
        "last_name": "Applicant",
        "email": "jane@example.com",
        "links": {"github": "https://github.com/jane", "linkedin": None, "portfolio": None},
    }
    assert data["job"]["title"] == "Backend Engineer" and data["job"]["slug"] == "backend-engineer"
    assert data["job"]["public_url"].endswith("/jobs/backend-engineer")
    assert data["admin_url"].endswith(f"/admin/applicants?selected={application.id}")
    assert {key: value for key, value in data["cv"].items() if key != "url"} == {
        "filename": "jane-cv.pdf",
        "size_bytes": 184233,
    }
    assert data["cv"]["url"].endswith(f"/api/v1/applications/{application.id}/cv")
    assert data["stage"] == "new" and data["source"] == "linkedin"
    assert data["applied_at"] == data["created_at"] == "2026-10-01T09:00:00+00:00"
    assert data["message"] == "Hi, I shipped two Next.js apps"
    assert data["quiz"] == {
        "status": "completed",
        "score_percent": 50,
        "completed_at": "2026-10-02T10:00:00+00:00",
        "flags": ["left the tab 2x"],
        "summary": "Ganek screening: 50% (2 questions), completed 2026-10-02, 1 integrity note",
    }
    text = json.dumps(data)
    for forbidden in (
        "correct_key",
        "question_ids",
        "q1",
        "raw-detail-text",
        "detail",
        "cv_object_key",
        "cvs/x/y.pdf",
        "internal note",
        "rejection",
        "screening_answers",
        "sq_1",
    ):
        assert forbidden not in text


def test_payload_without_attempt_has_null_quiz() -> None:
    application = payload_application(attempts=[])
    application.message = None
    application.candidate.links = {}
    data = webhooks.application_payload(application, sample_company())
    assert data["quiz"] is None
    assert data["message"] is None
    assert data["candidate"]["links"] == {"github": None, "linkedin": None, "portfolio": None}


def _attempt(
    status: AttemptStatus, flags: int = 0, completed: bool = True, questions: int = 4
) -> QuizAttempt:
    done = status is AttemptStatus.COMPLETED
    return QuizAttempt(
        status=status,
        score=0.83 if done else None,
        completed_at=datetime(2026, 10, 2, 10, 0, tzinfo=UTC) if done and completed else None,
        integrity={"flags": [{"summary": f"f{i}"} for i in range(flags)]},
        question_ids=[f"q{i}" for i in range(questions)],
    )


@pytest.mark.parametrize(
    ("attempt", "expected"),
    [
        (
            _attempt(AttemptStatus.COMPLETED),
            "Ganek screening: 83% (4 questions), completed 2026-10-02, no integrity notes",
        ),
        (
            _attempt(AttemptStatus.COMPLETED, questions=1),
            "Ganek screening: 83% (1 question), completed 2026-10-02, no integrity notes",
        ),
        (
            _attempt(AttemptStatus.COMPLETED, flags=2),
            "Ganek screening: 83% (4 questions), completed 2026-10-02, 2 integrity notes",
        ),
        (_attempt(AttemptStatus.PENDING), "Ganek screening: not completed (status pending)"),
        (_attempt(AttemptStatus.EXPIRED), "Ganek screening: not completed (status expired)"),
        (
            _attempt(AttemptStatus.COMPLETED, completed=False),
            "Ganek screening: not completed (status completed)",
        ),
    ],
)
def test_quiz_summary_wording(attempt: QuizAttempt, expected: str) -> None:
    assert webhooks.quiz_summary(attempt) == expected


@pytest.mark.parametrize("status", [AttemptStatus.PENDING, AttemptStatus.INVALIDATED])
def test_payload_of_an_unfinished_attempt_has_no_score(status: AttemptStatus) -> None:
    application = payload_application(attempts=[_attempt(status)])
    quiz = webhooks.application_payload(application, sample_company())["quiz"]
    assert quiz["status"] == status.value
    assert quiz["score_percent"] is None
    assert quiz["summary"] == f"Ganek screening: not completed (status {status.value})"


def test_sample_payload_matches_the_real_shape() -> None:
    company = Company(slug="acme", name="Acme", settings={})
    real = webhooks.application_payload(payload_application(), sample_company())
    sample = webhooks.sample_payload(company, "stage.changed", None)
    assert set(sample) == set(real) | {"previous_stage"}
    assert set(sample["candidate"]) == set(real["candidate"])
    assert set(sample["candidate"]["links"]) == set(real["candidate"]["links"])
    assert set(sample["job"]) == set(real["job"])
    assert set(sample["quiz"]) == set(real["quiz"])
    assert sample["job"]["public_url"].endswith("/jobs/sample-job")
    assert "cv" in sample and sample["cv"]["filename"] == "sample-candidate-cv.pdf"
    assert sample["stage"] == "interview" and sample["previous_stage"] == "screening"
    assert sample["candidate"]["email"] == "sample@example.invalid"
    # the hand-built summary must not drift from the real wording
    today = datetime.now(UTC)
    attempt = QuizAttempt(
        status=AttemptStatus.COMPLETED,
        score=0.83,
        completed_at=today,
        question_ids=[f"q{i}" for i in range(8)],
        integrity={},
    )
    assert sample["quiz"]["summary"] == webhooks.quiz_summary(attempt)
    assert sample["quiz"]["score_percent"] == 83 and sample["quiz"]["flags"] == []


def test_sample_payload_per_event() -> None:
    company = sample_company()
    created = webhooks.sample_payload(company, "application.created", None)
    assert created["stage"] == "new" and created["quiz"] is None
    assert "previous_stage" not in created
    done = webhooks.sample_payload(company, "quiz.completed", None)
    assert done["stage"] == "screening" and done["quiz"]["status"] == "completed"
    assert "previous_stage" not in done
    text = json.dumps([created, done])
    for forbidden in ("correct_key", "question_ids", "screening_answers", "cv_object_key"):
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
    assert ping.json()["event"] == "application.created" and ping.json()["status"] == "queued"
    deliveries = (await client.get(f"/api/v1/webhooks/{hook['id']}/deliveries")).json()
    assert [d["event"] for d in deliveries] == ["application.created"]
    assert (await client.get("/api/v1/webhooks")).json()[0]["last_delivery"]["status"] == "queued"

    assert (await client.delete(f"/api/v1/webhooks/{hook['id']}")).status_code == 204
    assert (await client.delete(f"/api/v1/webhooks/{hook['id']}")).status_code == 404
    assert (await client.get("/api/v1/webhooks")).json() == []
    types = [a["type"] for a in (await client.get("/api/v1/activity")).json()]
    assert types[:2] == ["webhook.deleted", "webhook.created"]


async def _queued_payload(ctx: Any, delivery_id: str) -> dict[str, Any]:
    async with ctx["session_factory"]() as db:
        row = await db.get(WebhookDelivery, UUID(delivery_id))
        assert row is not None
        return row.payload


@pytestmark_db
@pytest.mark.usefixtures("migrated_db", "multi_mode")
async def test_send_test_posts_a_sample_of_the_first_subscribed_event(
    client: AsyncClient, ctx: Any
) -> None:
    slug, _ = await _register(client)
    sample = (
        await client.post(
            "/api/v1/webhooks",
            json={
                "name": "Zap",
                "url": "https://hooks.example.com/zap",
                "events": ["quiz.completed", "stage.changed"],
            },
        )
    ).json()
    resp = await client.post(f"/api/v1/webhooks/{sample['id']}/test")
    assert resp.status_code == 202, resp.text
    assert resp.json()["event"] == "stage.changed"  # EVENTS order, not subscription order
    data = (await _queued_payload(ctx, resp.json()["id"]))["data"]
    assert data["test"] is True
    assert data["candidate"]["email"] == "sample@example.invalid"
    assert data["job"]["slug"] == "sample-job"

    # an endpoint with only the legacy ping event keeps the old body (the API
    # schema rejects it, so the row is created directly)
    async with ctx["session_factory"]() as db:
        company = (await db.execute(select(Company).where(Company.slug == slug))).scalar_one()
        endpoint, _secret = webhooks.new_endpoint(
            company, name="Legacy", url="https://hooks.example.com/ping", events=["ping"]
        )
        db.add(endpoint)
        await db.commit()
        endpoint_id = endpoint.id
    legacy = await client.post(f"/api/v1/webhooks/{endpoint_id}/test")
    assert legacy.status_code == 202, legacy.text
    assert legacy.json()["event"] == "ping"
    payload = await _queued_payload(ctx, legacy.json()["id"])
    assert payload["data"]["message"] == "Test delivery from Ganek"


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


@pytestmark_db
@pytest.mark.usefixtures("migrated_db", "multi_mode")
async def test_send_test_samples_the_newest_published_job_of_the_company(
    client: AsyncClient, ctx: Any
) -> None:
    slug, _ = await _register(client)
    resp = await client.post(
        "/api/v1/webhooks",
        json={"name": "Zap", "url": "https://hooks.example.com/zap", "events": ["quiz.completed"]},
    )
    endpoint_id = resp.json()["id"]
    now = datetime.now(UTC)
    tag = uuid4().hex[:6]
    async with ctx["session_factory"]() as db:
        company = (await db.execute(select(Company).where(Company.slug == slug))).scalar_one()
        other = Company(slug=f"other-{tag}", name="Other Co", settings={})
        db.add(other)
        await db.flush()

        def job(owner: Company, name: str, status: JobStatus, age_days: int | None) -> Job:
            return Job(
                company_id=owner.id,
                slug=f"{name}-{tag}",
                title=name,
                status=status,
                published_at=None if age_days is None else now - timedelta(days=age_days),
            )

        db.add_all(
            [
                job(company, "draft", JobStatus.DRAFT, 0),
                job(company, "undated", JobStatus.PUBLISHED, None),
                job(company, "older", JobStatus.PUBLISHED, 10),
                job(company, "newer", JobStatus.PUBLISHED, 5),
                job(other, "foreign", JobStatus.PUBLISHED, 1),
            ]
        )
        await db.commit()
    sent = await client.post(f"/api/v1/webhooks/{endpoint_id}/test")
    assert sent.status_code == 202, sent.text
    data = (await _queued_payload(ctx, sent.json()["id"]))["data"]
    assert data["job"]["slug"] == f"newer-{tag}"
