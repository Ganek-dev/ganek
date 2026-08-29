"""Recruiter anonymize-in-place (GDPR staff-account erasure).

Hard deletes are FK-blocked by interviews.interviewer_user_id (no
ondelete), so removal = tombstone email + null password/google_sub +
wiped availability + deleted Google credential + deactivate. The row
stays; the person is gone.
"""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from tests.db import database_reachable

pytestmark = pytest.mark.skipif(
    not database_reachable(),
    reason="database required (start postgres or use CI)",
)

PASSWORD = "a-long-secure-password"


@pytest.fixture
def multi_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "mode", "multi")


async def _company_with_member(
    client: AsyncClient,
) -> tuple[dict[str, str], dict[str, str], str]:
    """Register a company + one member. Ends logged in as the admin.

    Returns (admin_creds, member_creds, member_id).
    """
    admin = {"email": f"admin-{uuid4().hex[:8]}@ganek-ci.dev", "password": PASSWORD}
    resp = await client.post(
        "/api/v1/auth/register",
        json={"company_name": f"Anon Co {uuid4().hex[:6]}", **admin},
    )
    assert resp.status_code == 201, resp.text
    member = {"email": f"member-{uuid4().hex[:8]}@ganek-ci.dev", "password": PASSWORD}
    resp = await client.post("/api/v1/users", json={**member, "role": "member"})
    assert resp.status_code == 201, resp.text
    return admin, member, resp.json()["id"]


@pytest.mark.usefixtures("migrated_db", "multi_mode")
async def test_anonymize_tombstones_revokes_and_kills_sessions(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    from app.models import User, UserGoogleCredential

    admin, member, member_id = await _company_with_member(client)

    # a stored Google credential (undecryptable → no network on revoke)
    db_session.add(
        UserGoogleCredential(
            user_id=member_id,
            refresh_token_encrypted="not-decryptable",
            google_email=member["email"],
            connected_at=datetime.now(UTC),
        )
    )
    await db_session.commit()

    # capture a live member session cookie to prove it dies
    assert (await client.post("/api/v1/auth/login", json=member)).status_code == 200
    member_cookie = client.cookies.get("ganek_session")
    assert member_cookie
    assert (await client.post("/api/v1/auth/login", json=admin)).status_code == 200

    resp = await client.post(f"/api/v1/users/{member_id}/anonymize")
    assert resp.status_code == 204, resp.text

    # gone from the team list
    emails = [u["email"] for u in (await client.get("/api/v1/users")).json()]
    assert member["email"] not in emails
    assert not any(e.startswith("deleted-") for e in emails)

    # the row is a tombstone
    row = (await db_session.execute(select(User).where(User.id == member_id))).scalar_one()
    assert row.email.startswith("deleted-") and row.email.endswith("@invalid")
    assert row.password_hash is None
    assert row.google_sub is None
    assert row.interview_availability is None
    assert row.is_active is False

    # google credential deleted
    cred = (
        await db_session.execute(
            select(UserGoogleCredential).where(UserGoogleCredential.user_id == member_id)
        )
    ).scalar_one_or_none()
    assert cred is None

    # the captured session no longer works (token_version bumped)
    resp = await client.get("/api/v1/auth/me", headers={"Cookie": f"ganek_session={member_cookie}"})
    assert resp.status_code == 401
    # and the old password is dead too
    assert (await client.post("/api/v1/auth/login", json=member)).status_code == 401

    # anonymized receipt, PII-free
    assert (await client.post("/api/v1/auth/login", json=admin)).status_code == 200
    feed = (await client.get("/api/v1/activity")).json()
    entries = [e for e in feed if e["type"] == "user.anonymized"]
    assert len(entries) == 1
    assert entries[0]["payload"] == {}


@pytest.mark.usefixtures("migrated_db", "multi_mode")
async def test_anonymize_guards(client: AsyncClient, db_session: AsyncSession) -> None:
    from app.models import Application, Candidate, Interview, Job, User
    from app.models.interview import InterviewStatus

    admin, member, member_id = await _company_with_member(client)

    # member cannot anonymize anyone
    assert (await client.post("/api/v1/auth/login", json=member)).status_code == 200
    assert (await client.post(f"/api/v1/users/{member_id}/anonymize")).status_code == 403
    assert (await client.post("/api/v1/auth/login", json=admin)).status_code == 200

    # unknown id
    assert (await client.post(f"/api/v1/users/{uuid4()}/anonymize")).status_code == 404

    # the last active admin is protected
    admin_id = (await client.get("/api/v1/auth/me")).json()["id"]
    resp = await client.post(f"/api/v1/users/{admin_id}/anonymize")
    assert resp.status_code == 409

    # a member with an upcoming interview blocks with an actionable 409
    company_id = (
        await db_session.execute(select(User.company_id).where(User.id == member_id))
    ).scalar_one()
    job = Job(company_id=company_id, title="Guard Role", slug=f"guard-{uuid4().hex[:6]}")
    candidate = Candidate(
        company_id=company_id, email=f"c-{uuid4().hex[:8]}@ganek-ci.dev", name="C"
    )
    db_session.add_all([job, candidate])
    await db_session.flush()
    application = Application(
        company_id=company_id,
        job_id=job.id,
        candidate_id=candidate.id,
        cv_object_key=f"cvs/{company_id}/{uuid4().hex}",
        cv_filename="c.pdf",
        cv_size=1234,
    )
    db_session.add(application)
    await db_session.flush()
    db_session.add(
        Interview(
            company_id=company_id,
            application_id=application.id,
            interviewer_user_id=member_id,
            duration_minutes=30,
            timezone="Europe/Warsaw",
            status=InterviewStatus.BOOKED,
            scheduled_start=datetime.now(UTC) + timedelta(days=3),
        )
    )
    await db_session.commit()

    resp = await client.post(f"/api/v1/users/{member_id}/anonymize")
    assert resp.status_code == 409
    assert "interview" in resp.json()["detail"].lower()
