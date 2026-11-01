"""Candidate status page (screen 21): magic-link status + withdraw."""

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import delete, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models import ActivityLog
from app.models.quiz import AttemptAnswer
from app.services import email as email_service
from app.services import scheduled_emails
from tests.db import database_reachable, s3_reachable
from tests.helpers import upload_pdf
from tests.test_bulk_reject import _company_with_applicants, _ids_by_email

pytestmark = pytest.mark.skipif(
    not (database_reachable() and s3_reachable()),
    reason="database and object storage required (start postgres+minio or use CI)",
)

PDF_BYTES = b"%PDF-1.4 status flow"


@pytest.fixture
def multi_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "mode", "multi")


async def _apply(
    client: AsyncClient, *, with_quiz: bool = False
) -> tuple[dict[str, str | None], dict[str, str]]:
    """Register + publish + apply; returns (apply response json, admin creds)."""
    creds = {
        "email": f"admin-{uuid4().hex[:8]}@ganek-ci.dev",
        "password": "a-long-secure-password",
    }
    name = f"Status Co {uuid4().hex[:6]}"
    resp = await client.post("/api/v1/auth/register", json={"company_name": name, **creds})
    assert resp.status_code == 201, resp.text
    slug = name.lower().replace(" ", "-")
    job_payload: dict[str, object] = {"title": "Backend Engineer"}
    if with_quiz:
        job_payload["tags"] = ["python"]
        job_payload["quiz_config"] = {"enabled": True, "question_count": 2}
    job = (await client.post("/api/v1/jobs", json=job_payload)).json()
    assert (await client.post(f"/api/v1/jobs/{job['id']}/publish")).status_code == 200
    await client.post("/api/v1/auth/logout")

    base = f"/api/v1/public/companies/{slug}/jobs/{job['slug']}"
    ticket = (await client.post(f"{base}/apply/upload-url")).json()
    assert (await upload_pdf(ticket, PDF_BYTES)).is_success
    resp = await client.post(
        f"{base}/apply",
        json={
            "name": "Marta Vidal",
            "email": f"marta-{uuid4().hex[:8]}@ganek-ci.dev",
            "cv_object_key": ticket["object_key"],
            "cv_filename": "marta-vidal-cv.pdf",
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json(), creds


@pytest.mark.usefixtures("migrated_db", "bucket", "multi_mode")
async def test_apply_returns_status_token_and_status_renders(client: AsyncClient) -> None:
    received, _ = await _apply(client)
    token = received["status_token"]
    assert token

    resp = await client.get(f"/api/v1/public/applications/{token}")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["candidate_name"] == "Marta Vidal"
    assert body["company_name"].startswith("Status Co")
    assert body["job_title"] == "Backend Engineer"
    assert body["cv_filename"] == "marta-vidal-cv.pdf"
    assert body["stage"] == "new"
    assert body["quiz"] is None  # job had no assessment
    assert body["applied_at"] is not None
    assert body["decision_expected_by"] > body["applied_at"]


@pytest.mark.usefixtures("migrated_db", "seeded_bank", "bucket", "multi_mode")
async def test_status_shows_quiz_progress(client: AsyncClient) -> None:
    received, _ = await _apply(client, with_quiz=True)
    status_token = received["status_token"]
    quiz_token = received["quiz_token"]
    assert quiz_token

    body = (await client.get(f"/api/v1/public/applications/{status_token}")).json()
    assert body["quiz"] == {
        "status": "pending",
        "answered": 0,
        "timed_out": 0,
        "total": 2,
        "completed_at": None,
    }

    while True:
        step = (await client.post(f"/api/v1/public/quiz/{quiz_token}/next")).json()
        if step["done"]:
            break
        await client.post(
            f"/api/v1/public/quiz/{quiz_token}/answer",
            json={
                "question_id": step["question"]["id"],
                "answer_key": step["question"]["options"][0]["key"],
            },
        )

    body = (await client.get(f"/api/v1/public/applications/{status_token}")).json()
    assert body["quiz"]["status"] == "completed"
    assert body["quiz"]["answered"] == 2
    assert body["quiz"]["completed_at"] is not None
    # candidate-facing: the score must never appear
    assert "score" not in str(body)


@pytest.mark.usefixtures("migrated_db", "seeded_bank", "bucket", "multi_mode")
async def test_timed_out_questions_are_not_counted_as_answered(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """Demo review 2026-10-28, bug 1: a missed question showed up as answered."""
    received, _ = await _apply(client, with_quiz=True)
    status_token = received["status_token"]
    quiz_token = received["quiz_token"]
    assert quiz_token

    first = (await client.post(f"/api/v1/public/quiz/{quiz_token}/next")).json()
    assert first["question"]["index"] == 1
    # let the first question's deadline pass without an answer
    await db_session.execute(
        update(AttemptAnswer)
        .where(AttemptAnswer.question_id == first["question"]["id"])
        .values(deadline_at=datetime.now(UTC) - timedelta(seconds=1))
    )
    await db_session.commit()

    second = (await client.post(f"/api/v1/public/quiz/{quiz_token}/next")).json()
    assert second["done"] is False
    assert second["question"]["id"] != first["question"]["id"]
    # the missed question still takes its slot in the progression
    assert second["question"]["index"] == 2
    await client.post(
        f"/api/v1/public/quiz/{quiz_token}/answer",
        json={
            "question_id": second["question"]["id"],
            "answer_key": second["question"]["options"][0]["key"],
        },
    )
    assert (await client.post(f"/api/v1/public/quiz/{quiz_token}/next")).json()["done"] is True

    state = (await client.get(f"/api/v1/public/quiz/{quiz_token}")).json()
    assert state["status"] == "completed"
    assert state["answered"] == 1
    assert state["timed_out"] == 1
    assert state["total"] == 2

    body = (await client.get(f"/api/v1/public/applications/{status_token}")).json()
    assert body["quiz"]["status"] == "completed"
    assert body["quiz"]["answered"] == 1
    assert body["quiz"]["timed_out"] == 1
    assert body["quiz"]["total"] == 2


@pytest.mark.usefixtures("migrated_db", "bucket", "multi_mode")
async def test_withdraw_is_idempotent_and_final_stages_conflict(client: AsyncClient) -> None:
    received, creds = await _apply(client)
    token = received["status_token"]

    resp = await client.post(f"/api/v1/public/applications/{token}/withdraw")
    assert resp.status_code == 200
    body = (await client.get(f"/api/v1/public/applications/{token}")).json()
    assert body["stage"] == "withdrawn"

    # withdrawing again stays 200 (idempotent)
    assert (await client.post(f"/api/v1/public/applications/{token}/withdraw")).status_code == 200

    # a decided application cannot be withdrawn
    assert (await client.post("/api/v1/auth/login", json=creds)).status_code == 200
    app = (await client.get("/api/v1/applications")).json()["items"][0]
    resp = await client.patch(f"/api/v1/applications/{app['id']}/stage", json={"stage": "rejected"})
    assert resp.status_code == 200
    await client.post("/api/v1/auth/logout")
    assert (await client.post(f"/api/v1/public/applications/{token}/withdraw")).status_code == 409


def _later() -> str:
    return (datetime.now(UTC) + timedelta(days=1)).isoformat()


@pytest.fixture
def sent(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    captured: list[dict[str, Any]] = []
    monkeypatch.setattr(email_service, "send_rejection", lambda **kw: captured.append(kw))
    return captured


async def _public_stage(client: AsyncClient, token: str) -> str:
    return str((await client.get(f"/api/v1/public/applications/{token}")).json()["stage"])


@pytest.mark.usefixtures("migrated_db", "bucket", "multi_mode")
async def test_status_hides_a_scheduled_rejection_until_it_is_sent(
    client: AsyncClient, sent: list[dict[str, Any]]
) -> None:
    applicants, _ = await _company_with_applicants(client, 1, name_prefix="Hide Co")
    token = applicants[0]["status_token"]
    app_id = (await _ids_by_email(client))[applicants[0]["email"]]
    url = f"/api/v1/applications/{app_id}/stage"
    assert (await client.patch(url, json={"stage": "interview"})).status_code == 200
    resp = await client.patch(
        url, json={"stage": "rejected", "notify_candidate": True, "send_after": _later()}
    )
    assert resp.status_code == 200, resp.text

    assert await _public_stage(client, token) == "interview"
    # the staff view and the DSAR copy keep the truth
    bundle = (await client.get(f"/api/v1/applications/{app_id}/dsar-export")).json()
    assert bundle["applications"][0]["stage"] == "rejected"
    (mail,) = [e for e in bundle["applications"][0]["emails"] if e["kind"] == "rejection"]
    assert mail["status"] == "scheduled"
    assert mail["send_after"] is not None
    assert set(mail) == {"kind", "status", "send_after", "sent_at", "cancelled_at", "created_at"}

    emails = (await client.get(f"/api/v1/applications/{app_id}/emails")).json()
    (row,) = [e for e in emails if e["kind"] == "rejection"]
    cancel = await client.post(f"/api/v1/applications/{app_id}/emails/{row['id']}/cancel")
    assert cancel.status_code == 200, cancel.text
    # a cancelled hold is no longer scheduled: the page tells the truth
    assert await _public_stage(client, token) == "rejected"

    # reject again with send now
    resp = await client.patch(url, json={"stage": "rejected", "notify_candidate": True})
    assert resp.status_code == 200, resp.text
    assert await _public_stage(client, token) == "rejected"
    assert len(sent) == 1


@pytest.mark.usefixtures("migrated_db", "bucket", "multi_mode")
async def test_status_falls_back_to_screening_without_a_stage_move_entry(
    client: AsyncClient, db_session: AsyncSession, sent: list[dict[str, Any]]
) -> None:
    applicants, _ = await _company_with_applicants(client, 1, name_prefix="Fallback Co")
    token = applicants[0]["status_token"]
    app_id = (await _ids_by_email(client))[applicants[0]["email"]]
    resp = await client.patch(
        f"/api/v1/applications/{app_id}/stage",
        json={"stage": "rejected", "notify_candidate": True, "send_after": _later()},
    )
    assert resp.status_code == 200, resp.text
    assert await _public_stage(client, token) == "new"

    await db_session.execute(delete(ActivityLog).where(ActivityLog.application_id == app_id))
    await db_session.commit()
    assert await _public_stage(client, token) == "screening"


@pytest.mark.usefixtures("migrated_db", "bucket", "multi_mode")
async def test_withdraw_during_the_delay_cancels_the_mail(
    client: AsyncClient, sent: list[dict[str, Any]]
) -> None:
    applicants, _ = await _company_with_applicants(client, 2, name_prefix="Delay Co")
    ids = await _ids_by_email(client)
    token = applicants[0]["status_token"]
    app_id = ids[applicants[0]["email"]]
    resp = await client.patch(
        f"/api/v1/applications/{app_id}/stage",
        json={"stage": "rejected", "notify_candidate": True, "send_after": _later()},
    )
    assert resp.status_code == 200, resp.text

    resp = await client.post(f"/api/v1/public/applications/{token}/withdraw")
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"withdrawn": True}
    assert await _public_stage(client, token) == "withdrawn"

    items = (await client.get("/api/v1/applications")).json()["items"]
    item = next(i for i in items if i["id"] == app_id)
    assert item["stage"] == "withdrawn"
    assert item["rejection_reason"] == "withdrew"
    emails = (await client.get(f"/api/v1/applications/{app_id}/emails")).json()
    (row,) = [e for e in emails if e["kind"] == "rejection"]
    assert row["status"] == "cancelled"
    feed = [
        a for a in (await client.get("/api/v1/activity")).json() if a["type"] == "email.cancelled"
    ]
    assert len(feed) == 1
    assert feed[0]["actor_email"] is None
    assert sent == []

    # a rejection that was already sent stays final
    other_token = applicants[1]["status_token"]
    other_id = ids[applicants[1]["email"]]
    resp = await client.patch(
        f"/api/v1/applications/{other_id}/stage",
        json={"stage": "rejected", "notify_candidate": True},
    )
    assert resp.status_code == 200, resp.text
    resp = await client.post(f"/api/v1/public/applications/{other_token}/withdraw")
    assert resp.status_code == 409
    assert len(sent) == 1


@pytest.mark.usefixtures("migrated_db", "bucket", "multi_mode")
async def test_withdraw_loses_the_race_with_a_released_mail(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch, sent: list[dict[str, Any]]
) -> None:
    """The worker released the mail after the check: nothing is cancelled, so
    the withdrawal is rolled back and the decision stands."""
    applicants, _ = await _company_with_applicants(client, 1, name_prefix="Race Co")
    token = applicants[0]["status_token"]
    app_id = (await _ids_by_email(client))[applicants[0]["email"]]
    resp = await client.patch(
        f"/api/v1/applications/{app_id}/stage",
        json={"stage": "rejected", "notify_candidate": True, "send_after": _later()},
    )
    assert resp.status_code == 200, resp.text

    async def nothing_cancelled(*args: Any, **kwargs: Any) -> int:
        return 0

    monkeypatch.setattr(scheduled_emails, "cancel_for_application", nothing_cancelled)
    resp = await client.post(f"/api/v1/public/applications/{token}/withdraw")
    assert resp.status_code == 409
    items = (await client.get("/api/v1/applications")).json()["items"]
    assert next(i for i in items if i["id"] == app_id)["stage"] == "rejected"
    changes = [
        a for a in (await client.get("/api/v1/activity")).json() if a["type"] == "stage.changed"
    ]
    assert all(a["payload"]["to"] != "withdrawn" for a in changes)


@pytest.mark.usefixtures("migrated_db", "bucket", "multi_mode")
async def test_status_rejects_bad_tokens(client: AsyncClient) -> None:
    assert (await client.get("/api/v1/public/applications/not-a-token")).status_code == 404
    assert (
        await client.post("/api/v1/public/applications/not-a-token/withdraw")
    ).status_code == 404


@pytest.mark.usefixtures("migrated_db", "bucket", "multi_mode")
async def test_status_exposes_retention_and_privacy_url(client: AsyncClient) -> None:
    received, _ = await _apply(client)
    body = (await client.get(f"/api/v1/public/applications/{received['status_token']}")).json()
    assert body["retention_months"] == 6  # server-side default
    assert body["privacy_url"].endswith("/privacy")


@pytest.mark.usefixtures("migrated_db", "bucket", "multi_mode")
async def test_request_data_creates_task_and_activity(client: AsyncClient) -> None:
    from datetime import date, timedelta

    received, creds = await _apply(client)
    token = received["status_token"]

    resp = await client.post(f"/api/v1/public/applications/{token}/request-data")
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"status": "received"}

    assert (await client.post("/api/v1/auth/login", json=creds)).status_code == 200
    tasks = (await client.get("/api/v1/tasks")).json()
    matching = [t for t in tasks if t["title"] == "Privacy: data request - Marta Vidal"]
    assert len(matching) == 1
    assert "within one month" in matching[0]["note"]
    assert "marta-" in matching[0]["note"]  # candidate email so the admin can act
    assert matching[0]["due_date"] == (date.today() + timedelta(days=14)).isoformat()

    feed = (await client.get("/api/v1/activity")).json()
    entries = [e for e in feed if e["type"] == "candidate.data_requested"]
    assert len(entries) == 1
    assert entries[0]["payload"] == {}


@pytest.mark.usefixtures("migrated_db", "bucket", "multi_mode")
async def test_request_deletion_dedupes_open_task(client: AsyncClient) -> None:
    received, creds = await _apply(client)
    token = received["status_token"]

    assert (
        await client.post(f"/api/v1/public/applications/{token}/request-deletion")
    ).status_code == 200
    assert (
        await client.post(f"/api/v1/public/applications/{token}/request-deletion")
    ).status_code == 200

    assert (await client.post("/api/v1/auth/login", json=creds)).status_code == 200
    tasks = (await client.get("/api/v1/tasks")).json()
    matching = [t for t in tasks if t["title"] == "Privacy: deletion request - Marta Vidal"]
    assert len(matching) == 1  # second click did not stack a duplicate

    # ... but the activity trail keeps every request
    feed = (await client.get("/api/v1/activity")).json()
    assert len([e for e in feed if e["type"] == "candidate.deletion_requested"]) == 2


@pytest.mark.usefixtures("migrated_db", "bucket", "multi_mode")
async def test_privacy_requests_reject_bad_tokens(client: AsyncClient) -> None:
    assert (
        await client.post("/api/v1/public/applications/not-a-token/request-data")
    ).status_code == 404
    assert (
        await client.post("/api/v1/public/applications/not-a-token/request-deletion")
    ).status_code == 404
