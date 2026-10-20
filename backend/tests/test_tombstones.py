"""Erasure tombstones: erased rows that a backup restore brings back are
erased again by replay; receipts and tombstones survive."""

from typing import Any
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import func, insert, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models import ActivityLog, Application, Candidate, ErasureTombstone
from app.services import activity, storage, tombstones
from tests.db import database_reachable, s3_reachable
from tests.helpers import PDF_BYTES, upload_pdf

pytestmark = pytest.mark.skipif(
    not (database_reachable() and s3_reachable()),
    reason="database and object storage required (start postgres+minio or use CI)",
)

PASSWORD = "a-long-secure-password"


@pytest.fixture
def multi_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "mode", "multi")


async def _company_with_application(client: AsyncClient, db: AsyncSession) -> Application:
    """Registers an admin (session stays logged in) and one application;
    returns the application row (detached, with cv_object_key)."""
    name = f"Tomb Co {uuid4().hex[:6]}"
    admin_email = f"admin-{uuid4().hex[:8]}@ganek-ci.dev"
    resp = await client.post(
        "/api/v1/auth/register",
        json={"company_name": name, "email": admin_email, "password": PASSWORD},
    )
    assert resp.status_code == 201, resp.text
    company_id = UUID((await client.get("/api/v1/auth/me")).json()["company_id"])
    job = (await client.post("/api/v1/jobs", json={"title": "Backend Engineer"})).json()
    assert (await client.post(f"/api/v1/jobs/{job['id']}/publish")).status_code == 200
    await client.post("/api/v1/auth/logout")

    base = f"/api/v1/public/companies/{name.lower().replace(' ', '-')}/jobs/{job['slug']}"
    ticket = (await client.post(f"{base}/apply/upload-url")).json()
    assert (await upload_pdf(ticket)).is_success
    resp = await client.post(
        f"{base}/apply",
        json={
            "name": "Erased Person",
            "email": f"erased-{uuid4().hex[:8]}@ganek-ci.dev",
            "cv_object_key": ticket["object_key"],
            "cv_filename": "cv.pdf",
        },
    )
    assert resp.status_code == 201, resp.text

    login = await client.post(
        "/api/v1/auth/login", json={"email": admin_email, "password": PASSWORD}
    )
    assert login.status_code == 200, login.text
    application = (
        await db.execute(select(Application).where(Application.company_id == company_id))
    ).scalar_one()
    db.expunge(application)
    return application


def _columns(obj: Any, model: Any) -> dict[str, Any]:
    return {column.name: getattr(obj, column.name) for column in model.__table__.columns}


async def _receipts(db: AsyncSession, company_id: UUID) -> int:
    result = await db.execute(
        select(func.count())
        .select_from(ActivityLog)
        .where(ActivityLog.company_id == company_id, ActivityLog.type == activity.CANDIDATE_ERASED)
    )
    return int(result.scalar_one())


def test_subject_hash_is_blind_and_stable() -> None:
    an_id = uuid4()
    digest = tombstones.subject_hash(an_id)
    assert len(digest) == 64 and set(digest) <= set("0123456789abcdef")
    assert digest == tombstones.subject_hash(UUID(str(an_id)))
    assert digest != tombstones.subject_hash(uuid4())
    assert str(an_id) not in digest


@pytest.mark.usefixtures("migrated_db", "bucket", "multi_mode")
async def test_restore_after_erasure_is_replayed(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """create -> back up (snapshot rows) -> erase -> restore (re-insert) ->
    replay: the application is absent again, the receipt is kept."""
    application = await _company_with_application(client, db_session)
    candidate = (
        await db_session.execute(select(Candidate).where(Candidate.id == application.candidate_id))
    ).scalar_one()
    backup = {
        "candidate": _columns(candidate, Candidate),
        "application": _columns(application, Application),
    }
    db_session.expunge(candidate)

    resp = await client.post(f"/api/v1/applications/{application.id}/erase-candidate")
    assert resp.status_code == 200, resp.text
    assert await storage.stat_object(application.cv_object_key) is None
    assert await _receipts(db_session, application.company_id) == 1
    hashes = {
        row.subject_hash
        for row in (
            await db_session.execute(
                select(ErasureTombstone).where(
                    ErasureTombstone.company_id == application.company_id
                )
            )
        ).scalars()
    }
    assert hashes == {
        tombstones.subject_hash(application.id),
        tombstones.subject_hash(candidate.id),
    }

    # "restore": the rows and the CV object come back from the older backup
    await db_session.execute(insert(Candidate).values(**backup["candidate"]))
    await db_session.execute(insert(Application).values(**backup["application"]))
    await db_session.commit()
    await storage.put_object(application.cv_object_key, PDF_BYTES, "application/pdf")
    assert await storage.stat_object(application.cv_object_key) is not None

    summary = await tombstones.replay(db_session)
    assert summary.applications_erased == 1
    assert summary.candidates_erased == 1
    assert summary.storage_failures == 0
    assert (
        await db_session.execute(select(Application).where(Application.id == application.id))
    ).scalar_one_or_none() is None
    assert (
        await db_session.execute(select(Candidate).where(Candidate.id == candidate.id))
    ).scalar_one_or_none() is None
    assert await storage.stat_object(application.cv_object_key) is None
    assert await _receipts(db_session, application.company_id) == 1  # receipt untouched

    # idempotent, and the tombstones themselves stay for the next restore
    again = await tombstones.replay(db_session)
    assert (again.applications_erased, again.candidates_erased) == (0, 0)
    assert again.tombstones >= 2


@pytest.mark.usefixtures("migrated_db", "bucket", "multi_mode")
async def test_replay_leaves_live_rows_alone(client: AsyncClient, db_session: AsyncSession) -> None:
    application = await _company_with_application(client, db_session)
    summary = await tombstones.replay(db_session)
    assert summary.applications_erased == 0
    assert (
        await db_session.execute(select(Application).where(Application.id == application.id))
    ).scalar_one_or_none() is not None


@pytest.mark.usefixtures("migrated_db", "bucket", "multi_mode")
async def test_retention_style_application_erasure_leaves_a_tombstone(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    from app.services import erasure

    application = await _company_with_application(client, db_session)
    live = (
        await db_session.execute(select(Application).where(Application.id == application.id))
    ).scalar_one()
    await erasure.erase_application(db_session, live)
    await db_session.commit()
    row = await db_session.get(ErasureTombstone, tombstones.subject_hash(application.id))
    assert row is not None and row.kind == tombstones.APPLICATION
