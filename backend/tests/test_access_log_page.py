"""Company-wide read-access log (Settings > Privacy): filters, CSV, permissions."""

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


async def _admin_member_and_reads(
    client: AsyncClient,
) -> tuple[dict[str, str], dict[str, str], str, str, str]:
    """Admin opens the profile + CV, a member opens the profile. Returns
    (admin creds, member creds, admin id, member id, application id); the
    admin is logged in at the end."""
    _, admin = await _apply_with_quiz(client)
    application = await _login_and_get_application(client, admin)
    app_id = str(application["id"])
    admin_id = (await client.get("/api/v1/auth/me")).json()["id"]
    assert (await client.get(f"/api/v1/applications/{app_id}")).status_code == 200
    assert (await client.get(f"/api/v1/applications/{app_id}/cv-url")).status_code == 200
    member = {"email": f"member-{uuid4().hex[:8]}@ganek-ci.dev", "password": "member-password-1234"}
    member_id = (await client.post("/api/v1/users", json={**member, "role": "member"})).json()["id"]
    await client.post("/api/v1/auth/logout")
    assert (await client.post("/api/v1/auth/login", json=member)).status_code == 200
    assert (await client.get(f"/api/v1/applications/{app_id}")).status_code == 200
    await client.post("/api/v1/auth/logout")
    assert (await client.post("/api/v1/auth/login", json=admin)).status_code == 200
    return admin, member, admin_id, member_id, app_id


@pytest.mark.usefixtures("migrated_db", "seeded_bank", "bucket", "multi_mode")
async def test_company_log_lists_newest_first_with_candidate_and_filters(
    client: AsyncClient,
) -> None:
    admin, member, admin_id, member_id, app_id = await _admin_member_and_reads(client)

    page = (await client.get("/api/v1/access-log")).json()
    assert page["total"] == 3
    rows = page["items"]
    assert [(r["actor_email"], r["action"]) for r in rows] == [
        (member["email"], "view"),
        (admin["email"], "cv_download"),
        (admin["email"], "view"),
    ]
    assert rows[0]["candidate_name"] == "Tomas Hruby"
    assert rows[0]["job_title"] == "Backend Engineer"
    assert rows[0]["application_id"] == app_id

    by_member = (await client.get(f"/api/v1/access-log?actor_user_id={member_id}")).json()
    assert by_member["total"] == 1 and by_member["items"][0]["actor_email"] == member["email"]
    by_action = (await client.get("/api/v1/access-log?action=cv_download")).json()
    assert [r["action"] for r in by_action["items"]] == ["cv_download"]
    by_app = (await client.get(f"/api/v1/access-log?application_id={uuid4()}")).json()
    assert by_app == {"items": [], "total": 0}
    paged = (await client.get("/api/v1/access-log?limit=2&offset=2")).json()
    assert paged["total"] == 3 and len(paged["items"]) == 1
    assert paged["items"][0]["actor_email"] == admin["email"]
    # reading the company log is not a candidate read: the count is stable
    assert (await client.get("/api/v1/access-log")).json()["total"] == 3
    assert (await client.get(f"/api/v1/access-log?actor_user_id={admin_id}")).json()["total"] == 2


@pytest.mark.usefixtures("migrated_db", "seeded_bank", "bucket", "multi_mode")
async def test_company_log_is_admin_only_and_tenant_scoped(client: AsyncClient) -> None:
    _, member, _, _, _ = await _admin_member_and_reads(client)
    await client.post("/api/v1/auth/logout")
    assert (await client.get("/api/v1/access-log")).status_code == 401
    assert (await client.post("/api/v1/auth/login", json=member)).status_code == 200
    assert (await client.get("/api/v1/access-log")).status_code == 403
    assert (await client.get("/api/v1/access-log/export")).status_code == 403
    await client.post("/api/v1/auth/logout")
    # another company sees nothing of it
    _, other = await _apply_with_quiz(client)
    await _login_and_get_application(client, other)  # list view: not a read
    assert (await client.get("/api/v1/access-log")).json()["total"] == 0


@pytest.mark.usefixtures("migrated_db", "seeded_bank", "bucket", "multi_mode")
async def test_csv_export_carries_no_ids_and_lands_in_the_activity_log(
    client: AsyncClient,
) -> None:
    admin, member, admin_id, member_id, app_id = await _admin_member_and_reads(client)
    resp = await client.get("/api/v1/access-log/export?format=csv")
    assert resp.status_code == 200, resp.text
    assert resp.headers["content-type"].startswith("text/csv")
    assert 'filename="access-log-' in resp.headers["content-disposition"]
    lines = resp.text.strip().splitlines()
    assert lines[0] == "when,actor,action,candidate_name,candidate_email,job"
    assert len(lines) == 4
    assert member["email"] in lines[1] and "view" in lines[1]
    assert "Tomas Hruby" in lines[1] and "Backend Engineer" in lines[1]
    for internal in (app_id, admin_id, member_id):
        assert internal not in resp.text

    filtered = await client.get(f"/api/v1/access-log/export?format=csv&actor_user_id={member_id}")
    assert len(filtered.text.strip().splitlines()) == 2

    feed = (await client.get("/api/v1/activity")).json()
    exports = [a for a in feed if a["type"] == "access_log.exported"]
    assert len(exports) == 2
    assert exports[0]["actor_email"] == admin["email"]
    assert exports[0]["payload"]["rows"] == 1
    assert exports[0]["payload"]["actor_user_id"] == member_id
    assert exports[1]["payload"] == {
        "rows": 3,
        "actor_user_id": None,
        "api_key_id": None,
        "application_id": None,
        "action": None,
    }
