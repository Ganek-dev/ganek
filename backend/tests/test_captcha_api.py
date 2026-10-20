"""The proof-of-work gate on public forms (board card A5): signup, apply and
request-new-link reject a submission without a solved challenge with a
422 and a stable detail, accept a solved one, and stay untouched while
the feature is off."""

from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import ratelimit
from app.core.config import settings
from tests.db import database_reachable, s3_reachable
from tests.helpers import upload_pdf
from tests.test_attempt_reissue import (
    _apply_with_quiz,
    _expire_attempts,
    _login_and_get_application,
    _register_admin,
)
from tests.test_challenge import solve

pytestmark = pytest.mark.skipif(
    not (database_reachable() and s3_reachable()),
    reason="database and object storage required (start postgres+minio or use CI)",
)

PDF_BYTES = b"%PDF-1.4 captcha flow"


@pytest.fixture
def multi_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "mode", "multi")


def _enable_captcha(monkeypatch: pytest.MonkeyPatch) -> None:
    """Turned on AFTER the admin-side setup: the helpers register and
    publish without a token, exactly like an operator enabling it later."""
    monkeypatch.setattr(settings, "captcha_enabled", True)
    monkeypatch.setattr(settings, "captcha_secret", "s3cret")
    monkeypatch.setattr(settings, "captcha_max_number", 2_000)
    monkeypatch.setattr(ratelimit, "_get_redis", lambda: None)


async def _solved(client: AsyncClient) -> str:
    resp = await client.get("/api/v1/public/challenge")
    assert resp.status_code == 200, resp.text
    return solve(resp.json())


async def _published_job(client: AsyncClient) -> tuple[str, str]:
    creds, slug = await _register_admin(client)
    job = (await client.post("/api/v1/jobs", json={"title": "Backend Engineer"})).json()
    assert (await client.post(f"/api/v1/jobs/{job['id']}/publish")).status_code == 200
    await client.post("/api/v1/auth/logout")
    return slug, str(job["slug"])


async def _apply(client: AsyncClient, base: str, altcha: str | None) -> int:
    ticket = (await client.post(f"{base}/apply/upload-url")).json()
    assert (await upload_pdf(ticket, PDF_BYTES)).is_success
    body: dict[str, object] = {
        "name": "Tomas Hruby",
        "email": f"tomas-{uuid4().hex[:8]}@ganek-ci.dev",
        "cv_object_key": ticket["object_key"],
        "cv_filename": "tomas-cv.pdf",
    }
    if altcha is not None:
        body["altcha"] = altcha
    resp = await client.post(f"{base}/apply", json=body)
    return resp.status_code


@pytest.mark.usefixtures("migrated_db", "multi_mode")
async def test_challenge_endpoint_is_404_while_off(client: AsyncClient) -> None:
    assert (await client.get("/api/v1/public/challenge")).status_code == 404


@pytest.mark.usefixtures("migrated_db", "bucket", "multi_mode")
async def test_apply_requires_a_solved_challenge(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    slug, job_slug = await _published_job(client)
    _enable_captcha(monkeypatch)
    base = f"/api/v1/public/companies/{slug}/jobs/{job_slug}"

    assert await _apply(client, base, None) == 422
    bare = await client.post(
        f"{base}/apply",
        json={"name": "x", "email": "x@ganek-ci.dev", "cv_object_key": "k", "cv_filename": "a.pdf"},
    )
    assert bare.json()["detail"] == "captcha-required"
    assert await _apply(client, base, "garbage") == 422
    assert await _apply(client, base, await _solved(client)) == 201


@pytest.mark.usefixtures("migrated_db", "multi_mode")
async def test_signup_requires_a_solved_challenge(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _enable_captcha(monkeypatch)
    creds = {"email": f"admin-{uuid4().hex[:8]}@ganek-ci.dev", "password": "a-long-secure-password"}
    body = {"company_name": f"Captcha Co {uuid4().hex[:6]}", **creds}
    resp = await client.post("/api/v1/auth/register", json=body)
    assert resp.status_code == 422, resp.text
    assert resp.json()["detail"] == "captcha-required"
    resp = await client.post("/api/v1/auth/register", json={**body, "altcha": "nope"})
    assert resp.json()["detail"] == "captcha-invalid"
    resp = await client.post(
        "/api/v1/auth/register", json={**body, "altcha": await _solved(client)}
    )
    assert resp.status_code == 201, resp.text


@pytest.mark.usefixtures("migrated_db", "seeded_bank", "bucket", "multi_mode")
async def test_request_new_link_requires_a_solved_challenge(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    # set up with the gate off (the helpers apply without a token) ...
    applied, creds = await _apply_with_quiz(client)
    token = applied["quiz_token"]
    application = await _login_and_get_application(client, creds)
    await client.post("/api/v1/auth/logout")
    await _expire_attempts(db_session, str(application["id"]))

    # ... then turn it on for the candidate's request
    _enable_captcha(monkeypatch)
    url = f"/api/v1/public/quiz/{token}/request-reissue"
    assert (await client.post(url)).status_code == 422
    assert (await client.post(url, json={"altcha": "nope"})).json()["detail"] == "captcha-invalid"
    resp = await client.post(url, json={"altcha": await _solved(client)})
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"reissued": False}


@pytest.mark.usefixtures("migrated_db", "bucket", "multi_mode")
async def test_privacy_notice_announces_the_check(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    slug, _ = await _published_job(client)
    _enable_captcha(monkeypatch)
    notice = await client.get(f"/api/v1/public/companies/{slug}/privacy")
    assert notice.status_code == 200, notice.text
    assert notice.json()["captcha_enabled"] is True
