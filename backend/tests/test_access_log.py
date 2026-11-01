"""Read-access audit trail: who looked at which candidate (per-applicant view)."""

from uuid import uuid4

import pytest
from httpx import AsyncClient

from app.core.config import settings
from tests.db import database_reachable, s3_reachable
from tests.test_attempt_reissue import _apply_with_quiz, _login_and_get_application

pytestmark = pytest.mark.skipif(
    not (database_reachable() and s3_reachable()),
    reason="database and object storage required (start postgres+minio or use CI)",
)


@pytest.fixture
def multi_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "mode", "multi")


async def _admin_with_applicant(client: AsyncClient) -> tuple[dict[str, str], str]:
    """Register, publish a quiz job, apply, log back in; returns (creds, application id)."""
    _, creds = await _apply_with_quiz(client)
    application = await _login_and_get_application(client, creds)
    return creds, str(application["id"])


@pytest.mark.usefixtures("migrated_db", "seeded_bank", "bucket", "multi_mode")
async def test_detail_reads_are_recorded_once_per_window_with_the_actor(
    client: AsyncClient,
) -> None:
    creds, app_id = await _admin_with_applicant(client)
    base = f"/api/v1/applications/{app_id}"
    # the list is summary-level and is NOT logged
    assert (await client.get("/api/v1/applications")).status_code == 200
    assert (await client.get(f"{base}/access-log")).json() == []

    assert (await client.get(base)).status_code == 200
    assert (await client.get(base)).status_code == 200  # a refresh inside the window
    assert (await client.get(f"{base}/cv-url")).status_code == 200
    assert (await client.get(f"{base}/quiz-answers")).status_code == 200
    assert (await client.get(f"{base}/dsar-export")).status_code == 200

    rows = (await client.get(f"{base}/access-log")).json()
    assert [row["action"] for row in rows] == ["dsar_export", "quiz_answers", "cv_download", "view"]
    assert {row["actor_email"] for row in rows} == {creds["email"]}
    assert all(row["api_key_name"] is None for row in rows)
    assert all(row["created_at"] for row in rows)
    # reading the log is not itself a read of the candidate
    assert len((await client.get(f"{base}/access-log")).json()) == 4


@pytest.mark.usefixtures("migrated_db", "seeded_bank", "bucket", "multi_mode")
async def test_api_key_reads_record_the_key_and_keys_cannot_read_the_log(
    client: AsyncClient,
) -> None:
    creds, app_id = await _admin_with_applicant(client)
    secret = (
        await client.post("/api/v1/api-keys", json={"name": "ATS sync", "scope": "read"})
    ).json()["secret"]
    await client.post("/api/v1/auth/logout")
    bearer = {"Authorization": f"Bearer {secret}"}
    assert (await client.get(f"/api/v1/applications/{app_id}", headers=bearer)).status_code == 200
    # sessions only: the log is an admin surface, never an integration one
    assert (
        await client.get(f"/api/v1/applications/{app_id}/access-log", headers=bearer)
    ).status_code == 401

    assert (await client.post("/api/v1/auth/login", json=creds)).status_code == 200
    rows = (await client.get(f"/api/v1/applications/{app_id}/access-log")).json()
    assert len(rows) == 1
    assert rows[0]["action"] == "view"
    assert rows[0]["actor_email"] is None
    assert rows[0]["api_key_name"] == "ATS sync"


@pytest.mark.usefixtures("migrated_db", "seeded_bank", "bucket", "multi_mode")
async def test_api_key_fetches_the_cv_and_is_logged(client: AsyncClient) -> None:
    creds, app_id = await _admin_with_applicant(client)
    secret = (
        await client.post("/api/v1/api-keys", json={"name": "ATS sync", "scope": "read"})
    ).json()["secret"]
    write_secret = (
        await client.post("/api/v1/api-keys", json={"name": "Zap", "scope": "write"})
    ).json()["secret"]
    await client.post("/api/v1/auth/logout")
    bearer = {"Authorization": f"Bearer {secret}"}
    resp = await client.get(f"/api/v1/applications/{app_id}/cv", headers=bearer)
    assert resp.status_code == 302 and resp.headers["location"].startswith("http")
    # the presigned link is the whole credential: it carries its own signature
    assert "X-Amz-Signature" in resp.headers["location"]
    url = (await client.get(f"/api/v1/applications/{app_id}/cv-url", headers=bearer)).json()
    assert url["download_url"].startswith("http")
    write_resp = await client.get(
        f"/api/v1/applications/{app_id}/cv", headers={"Authorization": f"Bearer {write_secret}"}
    )
    assert write_resp.status_code == 302
    assert (
        await client.get(f"/api/v1/applications/{uuid4()}/cv", headers=bearer)
    ).status_code == 404
    assert (await client.get(f"/api/v1/applications/{app_id}/cv")).status_code == 401

    assert (await client.post("/api/v1/auth/login", json=creds)).status_code == 200
    rows = (await client.get(f"/api/v1/applications/{app_id}/access-log")).json()
    cv_rows = [r for r in rows if r["action"] == "cv_download"]
    # /cv and /cv-url by one key collapse into a single row inside the window.
    assert len(cv_rows) == 2
    assert {r["api_key_name"] for r in cv_rows} == {"ATS sync", "Zap"}


@pytest.mark.usefixtures("migrated_db", "seeded_bank", "bucket", "multi_mode")
async def test_other_company_and_revoked_key_get_404_and_401(client: AsyncClient) -> None:
    creds, app_id = await _admin_with_applicant(client)
    secret = (
        await client.post("/api/v1/api-keys", json={"name": "ATS sync", "scope": "read"})
    ).json()["secret"]
    await client.post("/api/v1/auth/logout")
    _, other_app_id = await _admin_with_applicant(client)  # a second company
    await client.post("/api/v1/auth/logout")
    bearer = {"Authorization": f"Bearer {secret}"}
    # another tenant's candidate is invisible, not forbidden
    other = await client.get(f"/api/v1/applications/{other_app_id}/cv", headers=bearer)
    assert other.status_code == 404
    assert (
        await client.get(f"/api/v1/applications/{app_id}/cv", headers=bearer)
    ).status_code == 302

    assert (await client.post("/api/v1/auth/login", json=creds)).status_code == 200
    key_id = (await client.get("/api/v1/api-keys")).json()[0]["id"]
    assert (await client.delete(f"/api/v1/api-keys/{key_id}")).status_code in (200, 204)
    await client.post("/api/v1/auth/logout")
    revoked = await client.get(f"/api/v1/applications/{app_id}/cv", headers=bearer)
    assert revoked.status_code == 401


@pytest.mark.usefixtures("migrated_db", "seeded_bank", "bucket", "multi_mode")
async def test_member_is_recorded_but_cannot_read_the_log(client: AsyncClient) -> None:
    creds, app_id = await _admin_with_applicant(client)
    member = {"email": f"member-{uuid4().hex[:8]}@ganek-ci.dev", "password": "member-password-1234"}
    assert (
        await client.post("/api/v1/users", json={**member, "role": "member"})
    ).status_code == 201
    await client.post("/api/v1/auth/logout")
    assert (await client.post("/api/v1/auth/login", json=member)).status_code == 200
    assert (await client.get(f"/api/v1/applications/{app_id}")).status_code == 200
    assert (await client.get(f"/api/v1/applications/{app_id}/access-log")).status_code == 403

    await client.post("/api/v1/auth/logout")
    assert (await client.post("/api/v1/auth/login", json=creds)).status_code == 200
    rows = (await client.get(f"/api/v1/applications/{app_id}/access-log")).json()
    assert [(row["actor_email"], row["action"]) for row in rows] == [(member["email"], "view")]


@pytest.mark.usefixtures("migrated_db", "seeded_bank", "bucket", "multi_mode")
async def test_access_log_is_tenant_scoped(client: AsyncClient) -> None:
    _, app_id = await _admin_with_applicant(client)
    await client.post("/api/v1/auth/logout")
    _, _ = await _admin_with_applicant(client)  # a second company, logged in
    assert (await client.get(f"/api/v1/applications/{app_id}/access-log")).status_code == 404
