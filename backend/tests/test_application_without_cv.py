"""An application created without a CV (0046): CSV import, the screen link and
connectors create these through the service; the public apply form still
requires a CV. Every surface shows "no CV" instead of a broken link or a 500."""

import json
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models import Company, Job
from app.models.webhook import WebhookDelivery
from app.schemas.public import ApplicationSubmit
from app.services import applications as applications_service
from app.services import webhooks
from tests.db import database_reachable, s3_reachable
from tests.test_webhooks import payload_application, sample_company

pytestmark_db = pytest.mark.skipif(
    not (database_reachable() and s3_reachable()),
    reason="database and object storage required (start postgres+minio or use CI)",
)


@pytest.fixture
def multi_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "mode", "multi")


# --- DB-free ---------------------------------------------------------------


def test_webhook_payload_has_null_cv_without_one() -> None:
    application = payload_application(attempts=[])
    application.cv_object_key = None
    application.cv_filename = None
    application.cv_size = None
    data = webhooks.application_payload(application, sample_company())
    assert data["cv"] is None


def test_export_row_has_blank_cv_filename_without_one() -> None:
    application = payload_application(attempts=[])
    application.cv_object_key = None
    application.cv_filename = None
    application.cv_size = None
    application.decided_at = None
    application.rejection_reason = None
    assert applications_service.export_row(application)["cv_filename"] == ""


async def test_service_still_requires_a_cv_by_default() -> None:
    payload = ApplicationSubmit(name="Jane", email="jane@example.com")
    with pytest.raises(applications_service.InvalidCvError):
        await applications_service.submit_application(
            None,  # type: ignore[arg-type]  # raises before touching the session
            sample_company(),
            Job(id=uuid4(), title="Backend Engineer", slug="backend-engineer"),
            payload,
        )


async def test_half_a_cv_is_refused_even_for_internal_callers() -> None:
    payload = ApplicationSubmit(name="Jane", email="jane@example.com", cv_filename="jane.pdf")
    with pytest.raises(applications_service.InvalidCvError):
        await applications_service.submit_application(
            None,  # type: ignore[arg-type]
            sample_company(),
            Job(id=uuid4(), title="Backend Engineer", slug="backend-engineer"),
            payload,
            allow_missing_cv=True,
        )


# --- DB ---------------------------------------------------------------------


@pytestmark_db
@pytest.mark.usefixtures("migrated_db", "bucket", "multi_mode")
async def test_application_without_cv_lists_exports_erases_and_delivers(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    creds = {
        "email": f"admin-{uuid4().hex[:8]}@ganek-ci.dev",
        "password": "a-long-secure-password",
    }
    name = f"NoCv Co {uuid4().hex[:6]}"
    resp = await client.post("/api/v1/auth/register", json={"company_name": name, **creds})
    assert resp.status_code == 201, resp.text
    slug = name.lower().replace(" ", "-")
    hook = (
        await client.post(
            "/api/v1/webhooks",
            json={
                "name": "All",
                "url": "https://hooks.example.com/all",
                "events": ["application.created"],
            },
        )
    ).json()
    job_out = (await client.post("/api/v1/jobs", json={"title": "Backend Engineer"})).json()
    assert (await client.post(f"/api/v1/jobs/{job_out['id']}/publish")).status_code == 200

    company = (await db_session.execute(select(Company).where(Company.slug == slug))).scalar_one()
    job = await db_session.get(Job, UUID(job_out["id"]))
    assert job is not None
    email = f"imported-{uuid4().hex[:8]}@ganek-ci.dev"
    application = await applications_service.submit_application(
        db_session,
        company,
        job,
        ApplicationSubmit(name="Imported Person", email=email, source="csv-import"),
        allow_missing_cv=True,
    )
    assert application.cv_object_key is None
    assert application.cv_filename is None and application.cv_size is None
    app_id = str(application.id)

    # list + detail
    items = (await client.get("/api/v1/applications")).json()["items"]
    assert [item["id"] for item in items] == [app_id]
    assert items[0]["cv_filename"] is None and items[0]["cv_size"] is None
    detail = await client.get(f"/api/v1/applications/{app_id}")
    assert detail.status_code == 200 and detail.json()["cv_filename"] is None

    # both CV routes answer 404 with a clear message, and log no download
    for path in ("cv", "cv-url"):
        resp = await client.get(f"/api/v1/applications/{app_id}/{path}", follow_redirects=False)
        assert resp.status_code == 404, resp.text
        assert resp.json()["detail"] == "This application has no CV"
    trail = (await client.get(f"/api/v1/applications/{app_id}/access-log")).json()
    assert [row["action"] for row in trail] == ["view"]  # the detail GET above, no download

    # export: the row is there with a blank filename
    exported = await client.get("/api/v1/applications/export", params={"format": "json"})
    assert exported.status_code == 200, exported.text
    rows = exported.json()
    rows = rows if isinstance(rows, list) else rows["items"]
    assert [row["candidate_email"] for row in rows] == [email]
    assert rows[0]["cv_filename"] == ""
    csv_export = await client.get("/api/v1/applications/export", params={"format": "csv"})
    assert csv_export.status_code == 200 and email in csv_export.text

    # DSAR bundle
    bundle = await client.get(f"/api/v1/applications/{app_id}/dsar-export")
    assert bundle.status_code == 200, bundle.text
    entry = bundle.json()["applications"][0]
    assert entry["cv_filename"] is None and entry["cv_download_url"] is None

    # webhook: application.created with cv null
    deliveries = (
        (
            await db_session.execute(
                select(WebhookDelivery).where(WebhookDelivery.endpoint_id == hook["id"])
            )
        )
        .scalars()
        .all()
    )
    assert [d.event for d in deliveries] == ["application.created"]
    assert deliveries[0].payload["data"]["cv"] is None
    assert "cv_object_key" not in json.dumps(deliveries[0].payload)

    # erasure: no CV object to delete, the rows still go
    resp = await client.post(f"/api/v1/applications/{app_id}/erase-candidate")
    assert resp.status_code == 200, resp.text
    assert resp.json()["applications"] == 1
    assert (await client.get(f"/api/v1/applications/{app_id}")).status_code == 404
