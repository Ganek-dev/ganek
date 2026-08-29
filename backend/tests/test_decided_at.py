"""The retention clock (G3): decided_at stamps on terminal stages, clears on
reopening. Stage history lives only in activity_log, so the purge needs this
column — migration 0020."""

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

PDF_BYTES = b"%PDF-1.4 decided-at flow"
PASSWORD = "a-long-secure-password"


@pytest.fixture
def multi_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "mode", "multi")


async def _company_with_applications(
    client: AsyncClient, *, n_candidates: int = 1
) -> list[dict[str, str]]:
    """One job, n candidates applied. Ends logged in as the admin.

    Returns per-candidate dicts {application_id, status_token}.
    """
    creds = {"email": f"admin-{uuid4().hex[:8]}@ganek-ci.dev", "password": PASSWORD}
    name = f"Clock Co {uuid4().hex[:6]}"
    resp = await client.post("/api/v1/auth/register", json={"company_name": name, **creds})
    assert resp.status_code == 201, resp.text
    slug = name.lower().replace(" ", "-")
    job = (await client.post("/api/v1/jobs", json={"title": "Role"})).json()
    assert (await client.post(f"/api/v1/jobs/{job['id']}/publish")).status_code == 200
    await client.post("/api/v1/auth/logout")

    base = f"/api/v1/public/companies/{slug}/jobs/{job['slug']}"
    token_by_email: dict[str, str] = {}
    for _ in range(n_candidates):
        ticket = (await client.post(f"{base}/apply/upload-url")).json()
        async with httpx.AsyncClient() as raw:
            put = await raw.put(
                ticket["upload_url"],
                content=PDF_BYTES,
                headers={"Content-Type": ticket["content_type"]},
            )
            assert put.status_code == 200
        email = f"cand-{uuid4().hex[:8]}@ganek-ci.dev"
        resp = await client.post(
            f"{base}/apply",
            json={
                "name": "Clock Candidate",
                "email": email,
                "cv_object_key": ticket["object_key"],
                "cv_filename": "cv.pdf",
            },
        )
        assert resp.status_code == 201, resp.text
        token_by_email[email] = resp.json()["status_token"]

    assert (await client.post("/api/v1/auth/login", json=creds)).status_code == 200
    apps = (await client.get("/api/v1/applications")).json()["items"]
    assert len(apps) == n_candidates
    # the list endpoint's ordering is not apply order — pair via candidate email
    return [
        {
            "application_id": app["id"],
            "status_token": token_by_email[app["candidate"]["email"]],
        }
        for app in apps
    ]


async def _decided_at(db: AsyncSession, application_id: str) -> object:
    from app.models import Application

    db.expire_all()  # the app commits in its own session; don't serve stale rows
    return (
        await db.execute(select(Application.decided_at).where(Application.id == application_id))
    ).scalar_one()


@pytest.mark.usefixtures("migrated_db", "bucket", "multi_mode")
async def test_stage_changes_stamp_and_clear_decided_at(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    (row,) = await _company_with_applications(client)
    app_id = row["application_id"]
    url = f"/api/v1/applications/{app_id}/stage"

    assert await _decided_at(db_session, app_id) is None

    assert (await client.patch(url, json={"stage": "rejected"})).status_code == 200
    assert await _decided_at(db_session, app_id) is not None

    # reopening clears the clock — a re-considered candidate must not be purged
    assert (await client.patch(url, json={"stage": "screening"})).status_code == 200
    assert await _decided_at(db_session, app_id) is None

    assert (await client.patch(url, json={"stage": "hired"})).status_code == 200
    assert await _decided_at(db_session, app_id) is not None


@pytest.mark.usefixtures("migrated_db", "bucket", "multi_mode")
async def test_bulk_reject_and_withdraw_stamp(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    rows = await _company_with_applications(client, n_candidates=2)

    resp = await client.post(
        "/api/v1/applications/bulk-reject",
        json={"application_ids": [rows[0]["application_id"]]},
    )
    assert resp.status_code == 200 and resp.json()["rejected"] == 1
    assert await _decided_at(db_session, rows[0]["application_id"]) is not None

    resp = await client.post(f"/api/v1/public/applications/{rows[1]['status_token']}/withdraw")
    assert resp.status_code == 200
    assert await _decided_at(db_session, rows[1]["application_id"]) is not None
