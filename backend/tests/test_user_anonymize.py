"""Recruiter anonymize-in-place (GDPR staff-account erasure).

Hard deletes are FK-blocked by interviews.interviewer_user_id (no
ondelete), so removal = tombstone email + null password/google_sub +
wiped availability + deleted Google credential + deactivate. The row
stays; the person is gone.
"""

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

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
    from app.models import User

    admin, member, member_id = await _company_with_member(client)

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


async def _scorecard_env(client: AsyncClient, db: AsyncSession) -> tuple[Any, Any, Any, Any]:
    """Company via the scorecards API helper (logged in as admin). Returns
    (co, application row, admin, member)."""
    from app.models import Application, User
    from tests.test_scorecards_api import _company

    co = await _company(client, db)
    app_row = await db.get(Application, co.application_id)
    admin = await db.get(User, co.admin_id)
    member = await db.get(User, co.member_id)
    assert app_row and admin and member
    return co, app_row, admin, member


async def _teammate(db: AsyncSession, admin: Any, **kw: Any) -> Any:
    from app.models import User, UserRole

    user = User(
        company_id=admin.company_id,
        email=f"mate-{uuid4().hex[:8]}@ganek-ci.dev",
        password_hash="x",
        role=UserRole.MEMBER,
        **kw,
    )
    db.add(user)
    await db.commit()
    return user


async def _payload_labels(db: AsyncSession, application_id: Any) -> list[Any]:
    from sqlalchemy import select

    from app.models import ActivityLog

    db.expire_all()
    rows = (
        await db.execute(
            select(ActivityLog).where(
                ActivityLog.application_id == UUID(str(application_id)),
                ActivityLog.type.like("scorecard.%"),
            )
        )
    ).scalars()
    return list(rows)


@pytest.mark.usefixtures("migrated_db", "multi_mode")
async def test_anonymize_dismisses_open_scorecards_and_relabels(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    from sqlalchemy import select

    from app.models import ActivityLog, Application, Candidate, Scorecard
    from app.services import scorecards as svc

    co, app_row, admin, member = await _scorecard_env(client, db_session)
    other = await _teammate(db_session, admin, display_name="Other Rev")
    member_label = member.display_label

    # a second application where the member already submitted
    cand2 = Candidate(company_id=app_row.company_id, email=f"c2-{uuid4().hex[:6]}@x.dev", name="B")
    db_session.add(cand2)
    await db_session.flush()
    app2 = Application(
        company_id=app_row.company_id,
        job_id=app_row.job_id,
        candidate_id=cand2.id,
        cv_object_key=f"cvs/{uuid4().hex}.pdf",
        cv_filename="cv.pdf",
        cv_size=1,
    )
    db_session.add(app2)
    await db_session.commit()
    app2_id = app2.id

    # app1: open row for the member, submitted row for the other reviewer
    await svc.request(db_session, application=app_row, reviewer=member, requested_by=admin)
    other_row = await svc.request(
        db_session, application=app_row, reviewer=other, requested_by=admin
    )
    await svc.submit(
        db_session,
        other_row,
        ratings={co.criterion_id: 4},
        recommendation=svc.Recommendation.STRONG_YES,
        comment="Great",
    )
    # app2: the member's own submitted row
    own_row = await svc.request(db_session, application=app2, reviewer=member, requested_by=admin)
    await svc.submit(
        db_session,
        own_row,
        ratings={co.criterion_id: 2},
        recommendation=svc.Recommendation.NO,
        comment="Not yet",
    )
    await db_session.commit()

    resp = await client.post(f"/api/v1/users/{co.member_id}/anonymize")
    assert resp.status_code == 204, resp.text

    listed = (await client.get(f"/api/v1/scorecards/applications/{co.application_id}")).json()
    by_state = {row["state"]: row for row in listed}
    assert by_state["dismissed"]["reviewer_label"] == "Former teammate"
    assert by_state["submitted"]["reviewer_label"] == "Other Rev"
    assert by_state["submitted"]["comment"] == "Great"

    db_session.expire_all()
    dismissed = (
        await db_session.execute(
            select(Scorecard).where(
                Scorecard.reviewer_user_id == UUID(co.member_id),
                Scorecard.application_id == UUID(co.application_id),
            )
        )
    ).scalar_one()
    assert str(dismissed.dismissed_by_user_id) == co.admin_id

    rows = await _payload_labels(db_session, co.application_id)
    labels = [r.payload.get("reviewer_label") for r in rows]
    assert member_label not in labels
    assert labels.count("Former teammate") == 2  # requested + dismissed
    assert labels.count("Other Rev") == 2  # requested + submitted, untouched
    dismissed_act = next(r for r in rows if r.type == "scorecard.dismissed")
    assert str(dismissed_act.actor_user_id) == co.admin_id  # spec 4.6

    # the member's submitted row elsewhere keeps its content, label rewritten
    kept = (
        await db_session.execute(select(Scorecard).where(Scorecard.application_id == app2_id))
    ).scalar_one()
    assert kept.comment == "Not yet" and kept.ratings == {co.criterion_id: 2}
    acts2 = (
        await db_session.execute(
            select(ActivityLog).where(
                ActivityLog.application_id == app2_id, ActivityLog.type == "scorecard.submitted"
            )
        )
    ).scalar_one()
    assert acts2.payload["reviewer_label"] == "Former teammate"


@pytest.mark.usefixtures("migrated_db", "multi_mode")
async def test_anonymize_scrubs_the_old_name_after_a_rename(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    from app.services import scorecards as svc

    co, app_row, admin, member = await _scorecard_env(client, db_session)
    member.display_name = "Jane Doe"
    await db_session.commit()
    row = await svc.request(db_session, application=app_row, reviewer=member, requested_by=admin)
    await svc.submit(
        db_session,
        row,
        ratings={co.criterion_id: 3},
        recommendation=svc.Recommendation.YES,
        comment=None,
    )
    member.display_name = "J. Doe"  # renamed after the labels were frozen
    await db_session.commit()

    resp = await client.post(f"/api/v1/users/{co.member_id}/anonymize")
    assert resp.status_code == 204, resp.text
    dump = str([r.payload for r in await _payload_labels(db_session, co.application_id)])
    assert "Jane Doe" not in dump and "J. Doe" not in dump
    assert "Former teammate" in dump


@pytest.mark.usefixtures("migrated_db", "multi_mode")
async def test_anonymize_leaves_a_same_named_colleague_alone(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    from app.services import scorecards as svc

    co, app_row, admin, member = await _scorecard_env(client, db_session)
    member.display_name = "Sam Twin"
    twin = await _teammate(db_session, admin, display_name="Sam Twin")
    await db_session.commit()
    await svc.request(db_session, application=app_row, reviewer=member, requested_by=admin)
    await svc.request(db_session, application=app_row, reviewer=twin, requested_by=admin)
    await db_session.commit()

    resp = await client.post(f"/api/v1/users/{co.member_id}/anonymize")
    assert resp.status_code == 204, resp.text
    labels = [
        r.payload.get("reviewer_label")
        for r in await _payload_labels(db_session, co.application_id)
    ]
    # twin's request row keeps the shared name; the member's dismissed and requested rows go
    assert labels.count("Sam Twin") == 1
    assert labels.count("Former teammate") == 2
