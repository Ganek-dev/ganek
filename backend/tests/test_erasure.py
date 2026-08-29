"""Candidate erasure (Art. 17) + email rectification (Art. 16).

Erasure must be fail-closed on storage (no rows disappear if S3 cleanup
fails — the cv_object_key pointer is the only way to find the object) and
best-effort on Google Calendar (events live on the recruiter's personal
calendar; a failure is reported, never blocking).
"""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import httpx
import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from tests.db import database_reachable, s3_reachable

pytestmark = pytest.mark.skipif(
    not (database_reachable() and s3_reachable()),
    reason="database and object storage required (start postgres+minio or use CI)",
)

PDF_BYTES = b"%PDF-1.4 erasure flow"
PASSWORD = "a-long-secure-password"


@pytest.fixture
def multi_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "mode", "multi")


async def _company_with_applications(
    client: AsyncClient, *, n_jobs: int = 1
) -> tuple[str, list[str]]:
    """Registers a company, publishes n jobs, applies to each with ONE email.

    Ends logged in as the admin; returns (candidate_email, status_tokens).
    """
    creds = {"email": f"admin-{uuid4().hex[:8]}@ganek-ci.dev", "password": PASSWORD}
    name = f"Erase Co {uuid4().hex[:6]}"
    resp = await client.post("/api/v1/auth/register", json={"company_name": name, **creds})
    assert resp.status_code == 201, resp.text
    slug = name.lower().replace(" ", "-")

    jobs = []
    for i in range(n_jobs):
        job = (await client.post("/api/v1/jobs", json={"title": f"Role {i}"})).json()
        assert (await client.post(f"/api/v1/jobs/{job['id']}/publish")).status_code == 200
        jobs.append(job)
    await client.post("/api/v1/auth/logout")

    email = f"cand-{uuid4().hex[:8]}@ganek-ci.dev"
    status_tokens: list[str] = []
    for job in jobs:
        base = f"/api/v1/public/companies/{slug}/jobs/{job['slug']}"
        ticket = (await client.post(f"{base}/apply/upload-url")).json()
        async with httpx.AsyncClient() as raw:
            put = await raw.put(
                ticket["upload_url"],
                content=PDF_BYTES,
                headers={"Content-Type": ticket["content_type"]},
            )
            assert put.status_code == 200
        resp = await client.post(
            f"{base}/apply",
            json={
                "name": "Erika Applicant",
                "email": email,
                "cv_object_key": ticket["object_key"],
                "cv_filename": "erika.pdf",
            },
        )
        assert resp.status_code == 201, resp.text
        status_tokens.append(resp.json()["status_token"])

    assert (await client.post("/api/v1/auth/login", json=creds)).status_code == 200
    return email, status_tokens


@pytest.mark.usefixtures("migrated_db", "bucket", "multi_mode")
async def test_erase_removes_rows_cv_and_writes_receipt(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    from app.models import Application
    from app.services import storage

    await _company_with_applications(client, n_jobs=2)
    apps = (await client.get("/api/v1/applications")).json()["items"]
    assert len(apps) == 2
    app_ids = [a["id"] for a in apps]
    keys = (
        (
            await db_session.execute(
                select(Application.cv_object_key).where(Application.id.in_(app_ids))
            )
        )
        .scalars()
        .all()
    )
    assert len(keys) == 2 and all(keys)

    resp = await client.post(f"/api/v1/applications/{app_ids[0]}/erase-candidate")
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"applications": 2, "google_event_failures": 0}

    # every application of the candidate is gone, tenant-wide
    for app_id in app_ids:
        assert (await client.get(f"/api/v1/applications/{app_id}")).status_code == 404
    assert (await client.get("/api/v1/applications")).json()["items"] == []

    # S3 objects really deleted
    for key in keys:
        assert await storage.stat_object(key) is None

    # the receipt is anonymized: count only, no candidate identity anywhere
    feed = (await client.get("/api/v1/activity")).json()
    erased = [e for e in feed if e["type"] == "candidate.erased"]
    assert len(erased) == 1
    assert erased[0]["payload"] == {"applications": 2, "tasks": 0}
    assert erased[0]["application_id"] is None
    # candidate-linked feed rows (application.received) cascaded away with the rows
    assert [e for e in feed if e["type"] == "application.received"] == []


@pytest.mark.usefixtures("migrated_db", "bucket", "multi_mode")
async def test_erase_invalidates_status_tokens(client: AsyncClient) -> None:
    _, status_tokens = await _company_with_applications(client, n_jobs=1)
    app_id = (await client.get("/api/v1/applications")).json()["items"][0]["id"]
    assert (await client.get(f"/api/v1/public/applications/{status_tokens[0]}")).status_code == 200

    assert (await client.post(f"/api/v1/applications/{app_id}/erase-candidate")).status_code == 200
    assert (await client.get(f"/api/v1/public/applications/{status_tokens[0]}")).status_code == 404


@pytest.mark.usefixtures("migrated_db", "bucket", "multi_mode")
async def test_erase_scrubs_privacy_request_tasks(client: AsyncClient) -> None:
    """The system-created request tasks name the candidate on purpose; they
    must not survive the erasure that fulfils them — open OR already done.
    A human task, even one shaped exactly like a request task, stays."""
    email, status_tokens = await _company_with_applications(client, n_jobs=1)
    app_id = (await client.get("/api/v1/applications")).json()["items"][0]["id"]

    # both request kinds through the real public endpoints (pins the format
    # the scrub matches against); one gets completed before the erasure
    token = status_tokens[0]
    assert (await client.post(f"/api/v1/public/applications/{token}/request-data")).status_code == (
        200
    )
    assert (
        await client.post(f"/api/v1/public/applications/{token}/request-deletion")
    ).status_code == 200
    tasks = (await client.get("/api/v1/tasks")).json()
    data_task = next(t for t in tasks if t["title"].startswith("Privacy: data request"))
    resp = await client.patch(f"/api/v1/tasks/{data_task['id']}", json={"done": True})
    assert resp.status_code == 200, resp.text

    # a recruiter's own note about the person — survives, whatever it says.
    # Created AFTER the requests: its request-shaped title would otherwise
    # trip the endpoint's open-task dedupe and suppress the system task.
    human = await client.post(
        "/api/v1/tasks",
        json={
            "title": "Privacy: deletion request — Erika Applicant",
            "note": f"Erika Applicant ({email}) asked me over the phone",
        },
    )
    assert human.status_code == 201, human.text

    assert (await client.post(f"/api/v1/applications/{app_id}/erase-candidate")).status_code == 200

    remaining = (await client.get("/api/v1/tasks", params={"include_done": True})).json()
    assert [t["id"] for t in remaining] == [human.json()["id"]]
    feed = (await client.get("/api/v1/activity")).json()
    erased = [e for e in feed if e["type"] == "candidate.erased"]
    assert erased[0]["payload"] == {"applications": 1, "tasks": 2}


@pytest.mark.usefixtures("migrated_db")
async def test_scrub_matches_email_literally(db_session: AsyncSession) -> None:
    """LIKE wildcards in the email must not widen the match: scrubbing
    a_b@x.dev may not take a lookalike axb@x.dev's request task with it."""
    from app.models import Company, Task
    from app.services import erasure

    company = Company(slug=f"scrub-{uuid4().hex[:8]}", name="Scrub Co", settings={})
    db_session.add(company)
    await db_session.flush()
    company_id = company.id  # plain value before expire_all (async lazy-refresh trap)

    def request_task(name: str, email: str) -> Task:
        return Task(
            company_id=company_id,
            created_by=None,
            title=f"Privacy: deletion request — {name}",
            note=f"{name} ({email}) asked via their status page (Role).",
        )

    lookalike = request_task("Ax B", "axb@x.dev")
    db_session.add_all([request_task("A B", "a_b@x.dev"), lookalike])
    await db_session.flush()
    lookalike_id = lookalike.id  # plain value before expire_all (async lazy-refresh trap)

    assert await erasure.scrub_privacy_request_tasks(db_session, company_id, "a_b@x.dev") == 1
    db_session.expire_all()
    remaining = (
        (await db_session.execute(select(Task.id).where(Task.company_id == company_id)))
        .scalars()
        .all()
    )
    assert remaining == [lookalike_id]


@pytest.mark.usefixtures("migrated_db", "bucket", "multi_mode")
async def test_erase_deletes_google_events_best_effort(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.models import Application, Interview, User
    from app.models.interview import InterviewStatus
    from app.services import erasure, google_calendar

    await _company_with_applications(client, n_jobs=1)
    app_id = (await client.get("/api/v1/applications")).json()["items"][0]["id"]
    application = (
        await db_session.execute(select(Application).where(Application.id == app_id))
    ).scalar_one()
    admin = (
        (await db_session.execute(select(User).where(User.company_id == application.company_id)))
        .scalars()
        .first()
    )
    assert admin is not None
    db_session.add(
        Interview(
            company_id=application.company_id,
            application_id=application.id,
            interviewer_user_id=admin.id,
            duration_minutes=30,
            timezone="Europe/Warsaw",
            status=InterviewStatus.BOOKED,
            scheduled_start=datetime.now(UTC) + timedelta(days=2),
            google_event_id="evt-1",
        )
    )
    db_session.add(
        Interview(
            company_id=application.company_id,
            application_id=application.id,
            interviewer_user_id=admin.id,
            duration_minutes=30,
            timezone="Europe/Warsaw",
            status=InterviewStatus.CANCELLED,
            google_event_id="evt-2",
        )
    )
    await db_session.commit()

    deleted: list[str] = []

    async def fake_delete(db: object, user: object, event_id: str) -> None:
        deleted.append(event_id)
        if event_id == "evt-1":
            raise google_calendar.GoogleCalendarError("google says no")

    monkeypatch.setattr(erasure.google_calendar, "delete_event", fake_delete)

    resp = await client.post(f"/api/v1/applications/{app_id}/erase-candidate")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["applications"] == 1
    assert body["google_event_failures"] == 1
    # every row with an event id is attempted, even cancelled history rows
    assert sorted(deleted) == ["evt-1", "evt-2"]
    # a Google failure never blocks the erasure itself
    assert (await client.get(f"/api/v1/applications/{app_id}")).status_code == 404


@pytest.mark.usefixtures("migrated_db", "bucket", "multi_mode")
async def test_erase_is_admin_only_and_tenant_scoped(client: AsyncClient) -> None:
    await _company_with_applications(client, n_jobs=1)
    app_id = (await client.get("/api/v1/applications")).json()["items"][0]["id"]

    member = {"email": f"member-{uuid4().hex[:8]}@ganek-ci.dev", "password": PASSWORD}
    resp = await client.post("/api/v1/users", json={**member, "role": "member"})
    assert resp.status_code == 201, resp.text
    await client.post("/api/v1/auth/logout")
    assert (await client.post("/api/v1/auth/login", json=member)).status_code == 200
    assert (await client.post(f"/api/v1/applications/{app_id}/erase-candidate")).status_code == 403

    await client.post("/api/v1/auth/logout")
    resp = await client.post(
        "/api/v1/auth/register",
        json={
            "company_name": f"Nosy Co {uuid4().hex[:6]}",
            "email": f"nosy-{uuid4().hex[:8]}@ganek-ci.dev",
            "password": PASSWORD,
        },
    )
    assert resp.status_code == 201
    assert (await client.post(f"/api/v1/applications/{app_id}/erase-candidate")).status_code == 404


@pytest.mark.usefixtures("migrated_db", "bucket", "multi_mode")
async def test_erase_fail_closed_when_storage_down(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.services import erasure

    await _company_with_applications(client, n_jobs=1)
    app_id = (await client.get("/api/v1/applications")).json()["items"][0]["id"]

    async def boom(object_key: str) -> None:
        raise RuntimeError("storage down")

    monkeypatch.setattr(erasure.storage, "delete_object", boom)

    with pytest.raises(RuntimeError, match="storage down"):
        await client.post(f"/api/v1/applications/{app_id}/erase-candidate")

    # nothing was committed — the application (and its cv pointer) survive
    assert (await client.get(f"/api/v1/applications/{app_id}")).status_code == 200


# --- Art. 16: edit candidate email -----------------------------------------


@pytest.mark.usefixtures("migrated_db", "bucket", "multi_mode")
async def test_email_update_roundtrip_and_guards(client: AsyncClient) -> None:
    await _company_with_applications(client, n_jobs=2)
    apps = (await client.get("/api/v1/applications")).json()["items"]
    app_id = apps[0]["id"]

    fixed = f"fixed-{uuid4().hex[:8]}@ganek-ci.dev"
    resp = await client.patch(
        f"/api/v1/applications/{app_id}/candidate-email", json={"email": fixed}
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["candidate"]["email"] == fixed
    # one candidate row → BOTH applications now show the corrected address
    other = (await client.get(f"/api/v1/applications/{apps[1]['id']}")).json()
    assert other["candidate"]["email"] == fixed

    # rectification leaves an anonymized trace
    feed = (await client.get("/api/v1/activity")).json()
    updated = [e for e in feed if e["type"] == "candidate.email_updated"]
    assert len(updated) == 1
    assert updated[0]["payload"] == {}

    # not an email at all → 422 from EmailStr
    resp = await client.patch(
        f"/api/v1/applications/{app_id}/candidate-email", json={"email": "not-an-email"}
    )
    assert resp.status_code == 422

    # member cannot rectify (admin-only)
    member = {"email": f"member-{uuid4().hex[:8]}@ganek-ci.dev", "password": PASSWORD}
    assert (
        await client.post("/api/v1/users", json={**member, "role": "member"})
    ).status_code == 201
    await client.post("/api/v1/auth/logout")
    assert (await client.post("/api/v1/auth/login", json=member)).status_code == 200
    assert (
        await client.patch(
            f"/api/v1/applications/{app_id}/candidate-email",
            json={"email": "x@ganek-ci.dev"},
        )
    ).status_code == 403


@pytest.mark.usefixtures("migrated_db", "bucket", "multi_mode")
async def test_email_update_409_when_taken_by_other_candidate(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    from app.models import Candidate

    await _company_with_applications(client, n_jobs=1)
    apps = (await client.get("/api/v1/applications")).json()["items"]
    app_id = apps[0]["id"]
    taken = f"taken-{uuid4().hex[:8]}@ganek-ci.dev"
    # second candidate row in the same company, no application needed
    company_id = (
        await db_session.execute(
            select(Candidate.company_id).where(Candidate.email == apps[0]["candidate"]["email"])
        )
    ).scalar_one()
    db_session.add(Candidate(company_id=company_id, email=taken, name="Other Person", links={}))
    await db_session.commit()

    resp = await client.patch(
        f"/api/v1/applications/{app_id}/candidate-email", json={"email": taken}
    )
    assert resp.status_code == 409
    # original untouched
    body = (await client.get(f"/api/v1/applications/{app_id}")).json()
    assert body["candidate"]["email"] != taken
