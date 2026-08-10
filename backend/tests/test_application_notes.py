"""Internal notes: CRUD, role rules, tenant isolation, no candidate leakage."""

from datetime import UTC, datetime
from uuid import uuid4

import httpx
import pytest
from httpx import AsyncClient

from app.core.config import settings
from tests.db import database_reachable, s3_reachable

pytestmark = pytest.mark.skipif(
    not (database_reachable() and s3_reachable()),
    reason="database and object storage required (start postgres+minio or use CI)",
)

PDF_BYTES = b"%PDF-1.4 notes flow"
QUIZ_CONFIG = {"enabled": True, "tags": ["python", "asyncio"], "question_count": 4}


@pytest.fixture
def multi_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "mode", "multi")


async def _company_with_applicant(client: AsyncClient) -> tuple[str, str, dict[str, str]]:
    """Registers a company, publishes a job, applies as a candidate.

    Ends logged in as the admin; returns (application_id, admin_email, admin_creds).
    """
    creds = {
        "email": f"admin-{uuid4().hex[:8]}@vetd-ci.dev",
        "password": "a-long-secure-password",
    }
    name = f"Notes Co {uuid4().hex[:6]}"
    resp = await client.post("/api/v1/auth/register", json={"company_name": name, **creds})
    assert resp.status_code == 201, resp.text
    slug = name.lower().replace(" ", "-")

    job = (await client.post("/api/v1/jobs", json={"title": "Backend Engineer"})).json()
    assert (await client.post(f"/api/v1/jobs/{job['id']}/publish")).status_code == 200
    await client.post("/api/v1/auth/logout")

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
            "name": "Jane Applicant",
            "email": f"cand-{uuid4().hex[:8]}@vetd-ci.dev",
            "cv_object_key": ticket["object_key"],
            "cv_filename": "jane.pdf",
        },
    )
    assert resp.status_code == 201, resp.text
    apply_body = resp.json()

    resp = await client.post("/api/v1/auth/login", json=creds)
    assert resp.status_code == 200
    application_id = (await client.get("/api/v1/applications")).json()[0]["id"]
    return application_id, creds["email"], {**creds, "status_token": apply_body["status_token"]}


async def _company_with_quiz_applicant(client: AsyncClient) -> tuple[str, str, str, str]:
    """Registers a company, publishes a quiz-enabled job, applies as a candidate.

    Returns (application_id, admin_email, quiz_token, status_token).
    Ends logged in as the admin.
    """
    creds = {
        "email": f"admin-{uuid4().hex[:8]}@vetd-ci.dev",
        "password": "a-long-secure-password",
    }
    name = f"Notes Quiz Co {uuid4().hex[:6]}"
    resp = await client.post("/api/v1/auth/register", json={"company_name": name, **creds})
    assert resp.status_code == 201, resp.text
    slug = name.lower().replace(" ", "-")

    job = (
        await client.post(
            "/api/v1/jobs",
            json={"title": "Python Dev", "tags": ["python", "asyncio"]},
        )
    ).json()

    # Enable quiz on the job
    from sqlalchemy import update
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from sqlalchemy.pool import NullPool

    from app.models import Job

    engine = create_async_engine(settings.database_url, poolclass=NullPool)
    async with async_sessionmaker(engine)() as db:
        await db.execute(update(Job).where(Job.id == job["id"]).values(quiz_config=QUIZ_CONFIG))
        await db.commit()
    await engine.dispose()

    assert (await client.post(f"/api/v1/jobs/{job['id']}/publish")).status_code == 200
    await client.post("/api/v1/auth/logout")

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
            "name": "Jane Quiz Applicant",
            "email": f"cand-{uuid4().hex[:8]}@vetd-ci.dev",
            "cv_object_key": ticket["object_key"],
            "cv_filename": "jane.pdf",
        },
    )
    assert resp.status_code == 201, resp.text
    apply_body = resp.json()

    resp = await client.post("/api/v1/auth/login", json=creds)
    assert resp.status_code == 200
    application_id = (await client.get("/api/v1/applications")).json()[0]["id"]
    return application_id, creds["email"], apply_body["quiz_token"], apply_body["status_token"]


@pytest.mark.usefixtures("migrated_db", "bucket", "multi_mode")
async def test_notes_roundtrip_and_order(client: AsyncClient) -> None:
    app_id, admin_email, _ = await _company_with_applicant(client)

    r = await client.post(f"/api/v1/applications/{app_id}/notes", json={"body": "first"})
    assert r.status_code == 201, r.text
    r2 = await client.post(f"/api/v1/applications/{app_id}/notes", json={"body": "second"})
    assert r2.status_code == 201, r2.text

    notes = (await client.get(f"/api/v1/applications/{app_id}/notes")).json()
    assert [n["body"] for n in notes] == ["first", "second"]
    assert notes[0]["author_email"] == admin_email
    assert notes[0]["id"]
    assert notes[0]["created_at"]


@pytest.mark.usefixtures("migrated_db", "bucket", "multi_mode")
async def test_notes_stable_order_on_created_at_tie(client: AsyncClient) -> None:
    """Two notes sharing a created_at (concurrent adds) must still sort the
    same way on every GET — break the tie on id, not left to Postgres's
    whim."""
    from sqlalchemy import update
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from sqlalchemy.pool import NullPool

    from app.models import ApplicationNote

    app_id, _, _ = await _company_with_applicant(client)

    note_a = (
        await client.post(f"/api/v1/applications/{app_id}/notes", json={"body": "note a"})
    ).json()
    note_b = (
        await client.post(f"/api/v1/applications/{app_id}/notes", json={"body": "note b"})
    ).json()

    # force a created_at tie, as concurrent adds would produce under load
    engine = create_async_engine(settings.database_url, poolclass=NullPool)
    async with async_sessionmaker(engine)() as db:
        tied_at = datetime.now(UTC)
        await db.execute(
            update(ApplicationNote)
            .where(ApplicationNote.id.in_([note_a["id"], note_b["id"]]))
            .values(created_at=tied_at)
        )
        await db.commit()
    await engine.dispose()

    expected_order = sorted([note_a["id"], note_b["id"]])
    for _ in range(3):
        notes = (await client.get(f"/api/v1/applications/{app_id}/notes")).json()
        assert [n["id"] for n in notes] == expected_order


@pytest.mark.usefixtures("migrated_db", "bucket", "multi_mode")
async def test_note_body_validation(client: AsyncClient) -> None:
    app_id, _, _ = await _company_with_applicant(client)

    assert (
        await client.post(f"/api/v1/applications/{app_id}/notes", json={"body": ""})
    ).status_code == 422
    assert (
        await client.post(f"/api/v1/applications/{app_id}/notes", json={"body": "x" * 4001})
    ).status_code == 422


@pytest.mark.usefixtures("migrated_db", "bucket", "multi_mode")
async def test_member_deletes_own_but_not_others(client: AsyncClient) -> None:
    app_id, _, admin_creds = await _company_with_applicant(client)

    member_pw = "member-password-1234"
    member_email = f"member-{uuid4().hex[:8]}@vetd-ci.dev"
    resp = await client.post(
        "/api/v1/users",
        json={"email": member_email, "password": member_pw, "role": "member"},
    )
    assert resp.status_code == 201, resp.text

    note_a = (
        await client.post(f"/api/v1/applications/{app_id}/notes", json={"body": "admin note"})
    ).json()

    async with AsyncClient(transport=client._transport, base_url="http://test") as member:
        assert (
            await member.post(
                "/api/v1/auth/login", json={"email": member_email, "password": member_pw}
            )
        ).status_code == 200
        note_b = (
            await member.post(f"/api/v1/applications/{app_id}/notes", json={"body": "member note"})
        ).json()

        # member cannot delete the admin's note
        resp = await member.delete(f"/api/v1/applications/{app_id}/notes/{note_a['id']}")
        assert resp.status_code == 403

        # member can delete their own note
        resp = await member.delete(f"/api/v1/applications/{app_id}/notes/{note_b['id']}")
        assert resp.status_code == 204

    # admin can delete the remaining note (theirs)
    resp = await client.delete(f"/api/v1/applications/{app_id}/notes/{note_a['id']}")
    assert resp.status_code == 204

    assert (await client.get(f"/api/v1/applications/{app_id}/notes")).json() == []


@pytest.mark.usefixtures("migrated_db", "bucket", "multi_mode")
async def test_tenant_isolation(client: AsyncClient) -> None:
    app_id, _, _ = await _company_with_applicant(client)
    await client.post(f"/api/v1/applications/{app_id}/notes", json={"body": "secret"})
    await client.post("/api/v1/auth/logout")

    resp = await client.post(
        "/api/v1/auth/register",
        json={
            "company_name": f"Other Co {uuid4().hex[:6]}",
            "email": f"other-{uuid4().hex[:8]}@vetd-ci.dev",
            "password": "a-long-secure-password",
        },
    )
    assert resp.status_code == 201

    assert (await client.get(f"/api/v1/applications/{app_id}/notes")).status_code == 404
    assert (
        await client.post(f"/api/v1/applications/{app_id}/notes", json={"body": "nope"})
    ).status_code == 404


@pytest.mark.usefixtures("migrated_db", "bucket", "multi_mode")
async def test_note_add_records_activity(client: AsyncClient) -> None:
    app_id, _, _ = await _company_with_applicant(client)
    assert (
        await client.post(f"/api/v1/applications/{app_id}/notes", json={"body": "first"})
    ).status_code == 201

    feed = (await client.get("/api/v1/activity")).json()
    types = [row["type"] for row in feed]
    assert "note.added" in types


@pytest.mark.usefixtures("migrated_db", "bucket", "multi_mode")
async def test_notes_never_in_candidate_payloads(client: AsyncClient) -> None:
    app_id, _, admin_creds = await _company_with_applicant(client)
    r = await client.post(f"/api/v1/applications/{app_id}/notes", json={"body": "first"})
    assert r.status_code == 201
    await client.post("/api/v1/auth/logout")

    resp = await client.get(f"/api/v1/public/applications/{admin_creds['status_token']}")
    assert resp.status_code == 200
    body = resp.json()
    assert "notes" not in body
    assert "first" not in resp.text


@pytest.mark.usefixtures("migrated_db", "seeded_bank", "bucket", "multi_mode")
async def test_notes_never_in_quiz_payload(client: AsyncClient) -> None:
    """Verify that internal notes never leak into the candidate-facing quiz payload."""
    app_id, _, quiz_token, _ = await _company_with_quiz_applicant(client)

    # Add a distinctive note
    distinctive_note = f"secret-admin-note-{uuid4().hex[:8]}"
    r = await client.post(f"/api/v1/applications/{app_id}/notes", json={"body": distinctive_note})
    assert r.status_code == 201

    await client.post("/api/v1/auth/logout")

    # Fetch the candidate-facing quiz payload
    resp = await client.get(f"/api/v1/public/quiz/{quiz_token}")
    assert resp.status_code == 200
    body = resp.json()

    # Assert note content is not present
    assert "notes" not in body
    assert distinctive_note not in resp.text
