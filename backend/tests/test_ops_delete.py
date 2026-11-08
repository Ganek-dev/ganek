"""Operator plane, tenant delete (board card "Operator plane"): guarded
(suspended first, slug typed back, never the operator's own workspace),
fail-closed on storage, and erasure-aware: blind tombstones outlive the
company, so a restored backup deletes the tenant again."""

from typing import Any
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import insert, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models import Application, Candidate, Company, ErasureTombstone, Job, User
from app.services import storage, tombstones
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


async def _tenant_with_application(client: AsyncClient) -> dict[str, Any]:
    """A tenant with one published job, one application with a CV, an
    orphaned CV upload and a logo. Ends logged out."""
    name = f"Gone Co {uuid4().hex[:6]}"
    email = f"admin-{uuid4().hex[:8]}@ganek-ci.dev"
    resp = await client.post(
        "/api/v1/auth/register", json={"company_name": name, "email": email, "password": PASSWORD}
    )
    assert resp.status_code == 201, resp.text
    company = (await client.get("/api/v1/company")).json()
    company_id = (await client.get("/api/v1/auth/me")).json()["company_id"]
    job = (await client.post("/api/v1/jobs", json={"title": "Backend Engineer"})).json()
    assert (await client.post(f"/api/v1/jobs/{job['id']}/publish")).status_code == 200
    await client.post("/api/v1/auth/logout")

    base = f"/api/v1/public/companies/{company['slug']}/jobs/{job['slug']}"
    ticket = (await client.post(f"{base}/apply/upload-url")).json()
    assert (await upload_pdf(ticket)).is_success
    applied = await client.post(
        f"{base}/apply",
        json={
            "name": "Deleted Person",
            "email": f"cand-{uuid4().hex[:8]}@ganek-ci.dev",
            "cv_object_key": ticket["object_key"],
            "cv_filename": "cv.pdf",
        },
    )
    assert applied.status_code == 201, applied.text

    orphan = f"{storage.cv_prefix(UUID(company_id))}orphan.pdf"
    await storage.put_object(orphan, PDF_BYTES, "application/pdf")
    logo = storage.build_logo_key(UUID(company_id))
    await storage.put_object(logo, b"\x89PNG logo", "image/png")
    return {
        "id": company_id,
        "slug": company["slug"],
        "email": email,
        "objects": [ticket["object_key"], orphan, logo],
    }


async def _operator(client: AsyncClient, monkeypatch: pytest.MonkeyPatch) -> str:
    """Registers the operator's own workspace, signs in and allow-lists them."""
    email = f"op-{uuid4().hex[:8]}@ganek-ci.dev"
    resp = await client.post(
        "/api/v1/auth/register",
        json={"company_name": f"Op Co {uuid4().hex[:6]}", "email": email, "password": PASSWORD},
    )
    assert resp.status_code == 201, resp.text
    monkeypatch.setattr(settings, "superadmin_user_ids", resp.json()["id"])
    return str((await client.get("/api/v1/auth/me")).json()["company_id"])


async def _delete(client: AsyncClient, company_id: str, slug: str) -> Any:
    return await client.request(
        "DELETE", f"/api/v1/ops/tenants/{company_id}", json={"confirm_slug": slug}
    )


async def _suspend(client: AsyncClient, company_id: str) -> None:
    resp = await client.post(
        f"/api/v1/ops/tenants/{company_id}/suspend", json={"reason": "Closing the account"}
    )
    assert resp.status_code == 200, resp.text


@pytest.mark.usefixtures("migrated_db", "bucket", "multi_mode")
async def test_delete_is_guarded_and_removes_the_whole_tenant(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    tenant = await _tenant_with_application(client)
    company_id = UUID(tenant["id"])
    application_id = await db_session.scalar(
        select(Application.id).where(Application.company_id == company_id)
    )
    candidate_id = await db_session.scalar(
        select(Candidate.id).where(Candidate.company_id == company_id)
    )
    own = await _operator(client, monkeypatch)

    assert (await _delete(client, str(uuid4()), "x")).status_code == 404
    # not suspended yet
    first = await _delete(client, tenant["id"], tenant["slug"])
    assert first.status_code == 409 and "Suspend" in first.json()["detail"]
    await _suspend(client, tenant["id"])
    # the slug must be typed back exactly
    wrong = await _delete(client, tenant["id"], "some-other-slug")
    assert wrong.status_code == 422
    assert (
        await client.request("DELETE", f"/api/v1/ops/tenants/{tenant['id']}", json={})
    ).status_code == 422
    # never the operator's own workspace, even suspended
    own_slug = (await client.get("/api/v1/company")).json()["slug"]
    await _suspend(client, own)
    mine = await _delete(client, own, own_slug)
    assert mine.status_code == 409 and "your own account" in mine.json()["detail"]
    assert (await client.post(f"/api/v1/ops/tenants/{own}/unsuspend")).status_code == 200
    for key in tenant["objects"]:
        assert await storage.stat_object(key) is not None  # nothing touched so far

    resp = await _delete(client, tenant["id"], tenant["slug"])
    assert resp.status_code == 200, resp.text
    assert resp.json() == {
        "id": tenant["id"],
        "slug": tenant["slug"],
        "users": 1,
        "jobs": 1,
        "candidates": 1,
        "applications": 1,
        "storage_objects": 2,
    }

    # rows: gone through the cascades
    for model in (User, Job, Candidate, Application):
        found = await db_session.scalar(select(model).where(model.company_id == company_id))
        assert found is None, model
    assert await db_session.get(Company, company_id) is None
    # objects: linked CV, orphaned CV and logo
    for key in tenant["objects"]:
        assert await storage.stat_object(key) is None
    # blind tombstones outlive the company (company_id set to NULL)
    for kind, subject in (
        (tombstones.COMPANY, company_id),
        (tombstones.CANDIDATE, candidate_id),
        (tombstones.APPLICATION, application_id),
    ):
        assert subject is not None
        row = await db_session.get(ErasureTombstone, tombstones.subject_hash(subject))
        assert row is not None and row.kind == kind and row.company_id is None

    # the tenant is gone from the list, its users cannot sign in, its page is a 404
    listed = (await client.get("/api/v1/ops/tenants")).json()
    assert tenant["id"] not in {t["id"] for t in listed}
    assert (await _delete(client, tenant["id"], tenant["slug"])).status_code == 404
    assert (await client.get(f"/api/v1/public/companies/{tenant['slug']}")).status_code == 404
    await client.post("/api/v1/auth/logout")
    login = await client.post(
        "/api/v1/auth/login", json={"email": tenant["email"], "password": PASSWORD}
    )
    assert login.status_code == 401


@pytest.mark.usefixtures("migrated_db", "bucket", "multi_mode")
async def test_delete_is_fail_closed_when_storage_cleanup_fails(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.services import erasure

    tenant = await _tenant_with_application(client)
    await _operator(client, monkeypatch)
    await _suspend(client, tenant["id"])

    async def partial(object_keys: list[str]) -> int:
        return len(object_keys) - 1

    monkeypatch.setattr(erasure.storage, "delete_objects", partial)
    resp = await _delete(client, tenant["id"], tenant["slug"])
    assert resp.status_code == 503
    assert "nothing was deleted" in resp.json()["detail"]
    assert await db_session.get(Company, UUID(tenant["id"])) is not None
    assert (
        await db_session.get(ErasureTombstone, tombstones.subject_hash(UUID(tenant["id"]))) is None
    )


@pytest.mark.usefixtures("migrated_db", "bucket", "multi_mode")
async def test_restored_tenant_is_deleted_again_by_replay(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    tenant = await _tenant_with_application(client)
    company_id = UUID(tenant["id"])
    company = await db_session.get(Company, company_id)
    assert company is not None
    backup = {c.name: getattr(company, c.name) for c in Company.__table__.columns}
    db_session.expunge(company)

    await _operator(client, monkeypatch)
    await _suspend(client, tenant["id"])
    assert (await _delete(client, tenant["id"], tenant["slug"])).status_code == 200

    # "restore": the company row and its logo come back from an older backup
    await db_session.execute(insert(Company).values(**backup))
    await db_session.commit()
    logo = storage.build_logo_key(company_id)
    await storage.put_object(logo, b"\x89PNG logo", "image/png")

    summary = await tombstones.replay(db_session)
    assert summary.companies_erased == 1 and summary.storage_failures == 0
    db_session.expire_all()
    assert await db_session.get(Company, company_id) is None
    assert await storage.stat_object(logo) is None
    # idempotent
    assert (await tombstones.replay(db_session)).companies_erased == 0
