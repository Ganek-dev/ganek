"""Dashboard v2 feeds: activity log, manual tasks, Today panel."""

from datetime import UTC, datetime, time, timedelta
from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models import (
    Application,
    AttemptStatus,
    Interview,
    InterviewStatus,
    Job,
    QuizAttempt,
    User,
)
from tests.db import database_reachable, s3_reachable
from tests.helpers import upload_pdf

pytestmark = pytest.mark.skipif(
    not (database_reachable() and s3_reachable()),
    reason="database and object storage required (start postgres+minio or use CI)",
)

PDF_BYTES = b"%PDF-1.4 dashboard flow"


@pytest.fixture
def multi_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "mode", "multi")


async def _company_with_applicant(client: AsyncClient) -> tuple[str, str, str]:
    """Returns (application_id, admin_user_id, admin_email), logged in as admin."""
    creds = {
        "email": f"admin-{uuid4().hex[:8]}@ganek-ci.dev",
        "password": "a-long-secure-password",
    }
    name = f"Dash Co {uuid4().hex[:6]}"
    resp = await client.post("/api/v1/auth/register", json={"company_name": name, **creds})
    assert resp.status_code == 201, resp.text
    admin_id = resp.json()["id"]
    slug = name.lower().replace(" ", "-")

    job = (await client.post("/api/v1/jobs", json={"title": "Backend Engineer"})).json()
    assert (await client.post(f"/api/v1/jobs/{job['id']}/publish")).status_code == 200
    await client.post("/api/v1/auth/logout")

    base = f"/api/v1/public/companies/{slug}/jobs/{job['slug']}"
    ticket = (await client.post(f"{base}/apply/upload-url")).json()
    assert (await upload_pdf(ticket, PDF_BYTES)).is_success
    resp = await client.post(
        f"{base}/apply",
        json={
            "name": "Marta Vidal",
            "email": f"cand-{uuid4().hex[:8]}@ganek-ci.dev",
            "cv_object_key": ticket["object_key"],
            "cv_filename": "marta.pdf",
        },
    )
    assert resp.status_code == 201, resp.text

    assert (await client.post("/api/v1/auth/login", json=creds)).status_code == 200
    application_id = (await client.get("/api/v1/applications")).json()["items"][0]["id"]
    return application_id, admin_id, creds["email"]


@pytest.mark.usefixtures("migrated_db", "bucket", "multi_mode")
async def test_activity_records_apply_and_stage_change(client: AsyncClient) -> None:
    application_id, _, admin_email = await _company_with_applicant(client)
    resp = await client.patch(
        f"/api/v1/applications/{application_id}/stage",
        json={"stage": "screening", "notify_candidate": False},
    )
    assert resp.status_code == 200

    feed = (await client.get("/api/v1/activity")).json()
    types = [row["type"] for row in feed]
    assert types[0] == "stage.changed"  # newest first
    assert "application.received" in types
    stage_row = feed[0]
    assert stage_row["actor_email"] == admin_email
    assert stage_row["payload"] == {"from": "new", "to": "screening"}
    received = next(row for row in feed if row["type"] == "application.received")
    assert received["actor_email"] is None  # candidate action
    assert received["payload"]["candidate"] == "Marta Vidal"


@pytest.mark.usefixtures("migrated_db", "bucket", "multi_mode")
async def test_activity_limit_clamped(client: AsyncClient) -> None:
    await _company_with_applicant(client)
    resp = await client.get("/api/v1/activity?limit=9999")
    assert resp.status_code == 200
    assert len(resp.json()) <= 50


@pytest.mark.usefixtures("migrated_db", "bucket", "multi_mode")
async def test_tasks_crud_and_tenancy(client: AsyncClient) -> None:
    await _company_with_applicant(client)
    created = await client.post(
        "/api/v1/tasks",
        json={"title": "Call Marta about the offer", "note": "before Friday"},
    )
    assert created.status_code == 201, created.text
    task = created.json()
    assert task["done_at"] is None

    open_tasks = (await client.get("/api/v1/tasks")).json()
    assert [t["id"] for t in open_tasks] == [task["id"]]

    done = await client.patch(f"/api/v1/tasks/{task['id']}", json={"done": True})
    assert done.json()["done_at"] is not None
    assert (await client.get("/api/v1/tasks")).json() == []
    assert len((await client.get("/api/v1/tasks?include_done=true")).json()) == 1

    reopened = await client.patch(f"/api/v1/tasks/{task['id']}", json={"done": False})
    assert reopened.json()["done_at"] is None
    assert (await client.delete(f"/api/v1/tasks/{task['id']}")).status_code == 204
    assert (await client.get("/api/v1/tasks")).json() == []

    # a second company must see none of this company's rows
    await client.post("/api/v1/auth/logout")
    await _company_with_applicant(client)
    assert (await client.get("/api/v1/tasks?include_done=true")).json() == []
    foreign = [row["type"] for row in (await client.get("/api/v1/activity")).json()]
    assert foreign == ["application.received"]


@pytest.mark.usefixtures("migrated_db", "bucket", "multi_mode")
async def test_today_lists_own_booked_interviews(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    application_id, admin_id, _ = await _company_with_applicant(client)
    from app.models import Application

    company_id = (
        await db_session.execute(
            select(Application.company_id).where(Application.id == application_id)
        )
    ).scalar_one()
    interview = Interview(
        company_id=company_id,
        application_id=application_id,
        interviewer_user_id=admin_id,
        duration_minutes=45,
        timezone="UTC",
        status=InterviewStatus.BOOKED,
        # keep the slot inside TODAY in UTC even when the suite runs near
        # midnight - now+2h would flake past 22:00 UTC otherwise
        scheduled_start=max(
            min(
                datetime.now(UTC) + timedelta(hours=2),
                datetime.combine(datetime.now(UTC).date(), time(23, 30), tzinfo=UTC),
            ),
            datetime.now(UTC) + timedelta(minutes=1),
        ),
        location="Room 2",
    )
    db_session.add(interview)
    await db_session.commit()

    resp = await client.get("/api/v1/stats/today?tz=not-a-real-zone")  # bad tz → UTC
    body = resp.json()
    assert set(body) == {"events"}
    assert len(body["events"]) == 1
    assert "Marta Vidal" in body["events"][0]["summary"]
    assert body["events"][0]["location"] == "Room 2"


@pytest.mark.usefixtures("migrated_db", "bucket", "multi_mode")
async def test_today_empty_without_anything(client: AsyncClient) -> None:
    await _company_with_applicant(client)
    body = (await client.get("/api/v1/stats/today")).json()
    assert body == {"events": []}


async def _queue_keys(client: AsyncClient) -> list[str]:
    resp = await client.get("/api/v1/stats/queue")
    assert resp.status_code == 200, resp.text
    return [item["key"] for item in resp.json()["items"]]


@pytest.mark.usefixtures("migrated_db", "bucket", "multi_mode")
async def test_queue_published_job_without_quiz(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    application_id, _, _ = await _company_with_applicant(client)
    job_id = (
        await db_session.execute(select(Application.job_id).where(Application.id == application_id))
    ).scalar_one()

    items = (await client.get("/api/v1/stats/queue")).json()["items"]
    assert [item["key"] for item in items] == [f"job-quiz:{job_id}"]
    assert items[0]["kind"] == "job-quiz"
    assert items[0]["title"] == "Add a quiz to Backend Engineer"
    assert items[0]["href"] == f"/admin/jobs/{job_id}/edit"

    # a draft never nags; neither does a job once its quiz is on
    await db_session.execute(
        update(Job)
        .where(Job.id == job_id)
        .values(quiz_config={"enabled": True, "tags": ["python"], "question_count": 2})
    )
    await db_session.commit()
    assert await _queue_keys(client) == []


@pytest.mark.usefixtures("migrated_db", "bucket", "multi_mode")
async def test_queue_integrity_flags_until_reviewed(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    application_id, _, _ = await _company_with_applicant(client)
    application = (
        await db_session.execute(select(Application).where(Application.id == application_id))
    ).scalar_one()
    await db_session.execute(
        update(Job)
        .where(Job.id == application.job_id)
        .values(quiz_config={"enabled": True, "tags": ["python"], "question_count": 2})
    )
    now = datetime.now(UTC)
    attempt = QuizAttempt(
        company_id=application.company_id,
        application_id=application.id,
        status=AttemptStatus.COMPLETED,
        question_ids=["q1", "q2"],
        started_at=now - timedelta(minutes=3),
        completed_at=now - timedelta(minutes=1),
        expires_at=now + timedelta(days=1),
        score=0.5,
        integrity={
            "flags": [
                {"code": "tab_hidden", "summary": "left the tab 3x (~40s)"},
                {"code": "paste", "summary": "paste detected x1"},
            ]
        },
    )
    db_session.add(attempt)
    await db_session.commit()

    items = (await client.get("/api/v1/stats/queue")).json()["items"]
    assert [item["key"] for item in items] == [f"integrity:{attempt.id}"]
    assert items[0]["title"] == "Review quiz flags: Marta Vidal"
    assert items[0]["hint"] == "Backend Engineer · left the tab 3x (~40s) · paste detected x1"
    assert items[0]["href"] == f"/admin/applicants?selected={application_id}"

    # "looks fine" on the applicant screen resolves it
    resp = await client.post(f"/api/v1/applications/{application_id}/quiz/dismiss-flags")
    assert resp.status_code == 200, resp.text
    assert await _queue_keys(client) == []


@pytest.mark.usefixtures("migrated_db", "bucket", "multi_mode")
async def test_queue_flags_ignored_once_application_closed(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    application_id, _, _ = await _company_with_applicant(client)
    application = (
        await db_session.execute(select(Application).where(Application.id == application_id))
    ).scalar_one()
    await db_session.execute(
        update(Job).where(Job.id == application.job_id).values(quiz_config={"enabled": True})
    )
    now = datetime.now(UTC)
    db_session.add(
        QuizAttempt(
            company_id=application.company_id,
            application_id=application.id,
            status=AttemptStatus.COMPLETED,
            question_ids=["q1"],
            completed_at=now,
            expires_at=now + timedelta(days=1),
            integrity={"flags": [{"code": "very_fast", "summary": "answered very fast"}]},
        )
    )
    await db_session.commit()
    assert len(await _queue_keys(client)) == 1

    resp = await client.patch(
        f"/api/v1/applications/{application_id}/stage",
        json={"stage": "rejected", "notify_candidate": False},
    )
    assert resp.status_code == 200, resp.text
    assert await _queue_keys(client) == []


@pytest.mark.usefixtures("migrated_db", "bucket", "multi_mode")
async def test_queue_unbooked_interview_until_booked(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    application_id, admin_id, _ = await _company_with_applicant(client)
    application = (
        await db_session.execute(select(Application).where(Application.id == application_id))
    ).scalar_one()
    await db_session.execute(
        update(Job).where(Job.id == application.job_id).values(quiz_config={"enabled": True})
    )
    interview = Interview(
        company_id=application.company_id,
        application_id=application.id,
        interviewer_user_id=admin_id,
        duration_minutes=30,
        timezone="UTC",
        status=InterviewStatus.PENDING,
    )
    db_session.add(interview)
    await db_session.commit()

    items = (await client.get("/api/v1/stats/queue")).json()["items"]
    assert [item["key"] for item in items] == [f"unbooked:{interview.id}"]
    assert items[0]["title"] == "Awaiting booking: Marta Vidal"
    assert items[0]["hint"] == "Backend Engineer · Hiring manager interview"
    assert items[0]["href"] == f"/admin/applicants?selected={application_id}"

    interview.status = InterviewStatus.BOOKED
    interview.scheduled_start = datetime.now(UTC) + timedelta(days=1)
    await db_session.commit()
    assert await _queue_keys(client) == []


@pytest.mark.usefixtures("migrated_db", "bucket", "multi_mode")
async def test_queue_dismiss_is_per_user_and_pruned(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    application_id, admin_id, _ = await _company_with_applicant(client)
    job_id = (
        await db_session.execute(select(Application.job_id).where(Application.id == application_id))
    ).scalar_one()
    key = f"job-quiz:{job_id}"
    assert await _queue_keys(client) == [key]

    resp = await client.post("/api/v1/stats/queue/dismiss", json={"key": key})
    assert resp.status_code == 204, resp.text
    assert await _queue_keys(client) == []
    # idempotent; a key the server never produced is refused
    assert (await client.post("/api/v1/stats/queue/dismiss", json={"key": key})).status_code == 204
    resp = await client.post("/api/v1/stats/queue/dismiss", json={"key": "job-quiz:nope"})
    assert resp.status_code == 404
    stored = (
        await db_session.execute(select(User.queue_dismissed).where(User.id == admin_id))
    ).scalar_one()
    assert stored == [key]

    # the item resolves (quiz enabled): the stale key leaves the user row,
    # so switching the quiz off again surfaces the item once more
    await db_session.execute(
        update(Job).where(Job.id == job_id).values(quiz_config={"enabled": True})
    )
    await db_session.commit()
    assert await _queue_keys(client) == []
    stored = (
        await db_session.execute(select(User.queue_dismissed).where(User.id == admin_id))
    ).scalar_one()
    assert stored is None
    await db_session.execute(
        update(Job).where(Job.id == job_id).values(quiz_config={"enabled": False})
    )
    await db_session.commit()
    assert await _queue_keys(client) == [key]

    # another company sees nothing of this one, and cannot dismiss its keys
    await client.post("/api/v1/auth/logout")
    other_application_id, _, _ = await _company_with_applicant(client)
    other_job_id = (
        await db_session.execute(
            select(Application.job_id).where(Application.id == other_application_id)
        )
    ).scalar_one()
    assert await _queue_keys(client) == [f"job-quiz:{other_job_id}"]
    resp = await client.post("/api/v1/stats/queue/dismiss", json={"key": key})
    assert resp.status_code == 404
