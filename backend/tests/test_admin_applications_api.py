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

PDF_BYTES = b"%PDF-1.4 admin flow"


@pytest.fixture
def multi_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "mode", "multi")


async def _company_with_applicant(
    client: AsyncClient, *, with_quiz: bool = False
) -> tuple[str, str]:
    """Registers a company, publishes a job, applies as a candidate.

    Ends logged in as the admin; returns (job_id, candidate_email).
    """
    creds = {
        "email": f"admin-{uuid4().hex[:8]}@ganek-ci.dev",
        "password": "a-long-secure-password",
    }
    name = f"Hire Co {uuid4().hex[:6]}"
    resp = await client.post("/api/v1/auth/register", json={"company_name": name, **creds})
    assert resp.status_code == 201, resp.text
    slug = name.lower().replace(" ", "-")

    job_payload: dict[str, object] = {"title": "Backend Engineer"}
    if with_quiz:
        job_payload["tags"] = ["python"]
        job_payload["quiz_config"] = {"enabled": True, "question_count": 2}
    job = (await client.post("/api/v1/jobs", json=job_payload)).json()
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
    email = f"cand-{uuid4().hex[:8]}@ganek-ci.dev"
    resp = await client.post(
        f"{base}/apply",
        json={
            "name": "Jane Applicant",
            "email": email,
            "message": "Hello!",
            "cv_object_key": ticket["object_key"],
            "cv_filename": "jane.pdf",
        },
    )
    assert resp.status_code == 201, resp.text

    resp = await client.post("/api/v1/auth/login", json=creds)
    assert resp.status_code == 200
    return job["id"], email


@pytest.mark.usefixtures("migrated_db", "bucket", "multi_mode")
async def test_admin_lists_and_advances_application(client: AsyncClient) -> None:
    job_id, email = await _company_with_applicant(client)

    apps = (await client.get("/api/v1/applications")).json()["items"]
    assert len(apps) == 1
    app = apps[0]
    assert app["candidate"]["email"] == email
    assert app["stage"] == "new"
    assert app["cv_filename"] == "jane.pdf"
    assert "cv_object_key" not in app  # storage internals stay internal

    # filters
    assert (await client.get(f"/api/v1/applications?job_id={job_id}")).json()["items"] != []
    assert (await client.get("/api/v1/applications?stage=rejected")).json()["items"] == []

    # stage change
    resp = await client.patch(
        f"/api/v1/applications/{app['id']}/stage", json={"stage": "screening"}
    )
    assert resp.status_code == 200
    assert resp.json()["stage"] == "screening"

    # CV download really works via the presigned URL
    resp = await client.get(f"/api/v1/applications/{app['id']}/cv-url")
    assert resp.status_code == 200
    async with httpx.AsyncClient() as raw:
        got = await raw.get(resp.json()["download_url"])
        assert got.status_code == 200
        assert got.content == PDF_BYTES
        assert 'filename="jane.pdf"' in got.headers.get("content-disposition", "")


@pytest.mark.usefixtures("migrated_db", "bucket", "multi_mode")
async def test_applications_require_auth_and_are_tenant_scoped(client: AsyncClient) -> None:
    await _company_with_applicant(client)
    target = (await client.get("/api/v1/applications")).json()["items"][0]

    await client.post("/api/v1/auth/logout")
    assert (await client.get("/api/v1/applications")).status_code == 401

    # a different company sees nothing and cannot touch the application
    resp = await client.post(
        "/api/v1/auth/register",
        json={
            "company_name": f"Other Co {uuid4().hex[:6]}",
            "email": f"other-{uuid4().hex[:8]}@ganek-ci.dev",
            "password": "a-long-secure-password",
        },
    )
    assert resp.status_code == 201
    assert (await client.get("/api/v1/applications")).json()["items"] == []
    assert (await client.get(f"/api/v1/applications/{target['id']}")).status_code == 404
    assert (
        await client.patch(f"/api/v1/applications/{target['id']}/stage", json={"stage": "hired"})
    ).status_code == 404
    assert (await client.get(f"/api/v1/applications/{target['id']}/cv-url")).status_code == 404


@pytest.mark.usefixtures("migrated_db", "seeded_bank", "bucket", "multi_mode")
async def test_admin_sees_quiz_results(client: AsyncClient) -> None:
    from sqlalchemy import update
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from sqlalchemy.pool import NullPool

    from app.models import Job

    creds = {
        "email": f"admin-{uuid4().hex[:8]}@ganek-ci.dev",
        "password": "a-long-secure-password",
    }
    name = f"Score Co {uuid4().hex[:6]}"
    assert (
        await client.post("/api/v1/auth/register", json={"company_name": name, **creds})
    ).status_code == 201
    slug = name.lower().replace(" ", "-")
    job = (await client.post("/api/v1/jobs", json={"title": "Py Dev", "tags": ["python"]})).json()
    engine = create_async_engine(settings.database_url, poolclass=NullPool)
    async with async_sessionmaker(engine)() as db:
        await db.execute(
            update(Job)
            .where(Job.id == job["id"])
            .values(quiz_config={"enabled": True, "tags": ["python"], "question_count": 2})
        )
        await db.commit()
    await engine.dispose()
    assert (await client.post(f"/api/v1/jobs/{job['id']}/publish")).status_code == 200
    await client.post("/api/v1/auth/logout")

    base = f"/api/v1/public/companies/{slug}/jobs/{job['slug']}"
    ticket = (await client.post(f"{base}/apply/upload-url")).json()
    async with httpx.AsyncClient() as raw:
        assert (
            await raw.put(
                ticket["upload_url"],
                content=PDF_BYTES,
                headers={"Content-Type": ticket["content_type"]},
            )
        ).status_code == 200
    resp = await client.post(
        f"{base}/apply",
        json={
            "name": "Jane",
            "email": f"jane-{uuid4().hex[:8]}@ganek-ci.dev",
            "cv_object_key": ticket["object_key"],
            "cv_filename": "cv.pdf",
        },
    )
    token = resp.json()["quiz_token"]
    assert token is not None
    while True:
        body = (await client.post(f"/api/v1/public/quiz/{token}/next")).json()
        if body["done"]:
            break
        question = body["question"]
        await client.post(
            f"/api/v1/public/quiz/{token}/answer",
            json={"question_id": question["id"], "answer_key": question["options"][0]["key"]},
        )

    assert (await client.post("/api/v1/auth/login", json=creds)).status_code == 200
    app = (await client.get("/api/v1/applications")).json()["items"][0]
    result = app["quiz_attempt"]
    assert result is not None
    assert result["status"] == "completed"
    assert result["score"] is not None
    assert 0.0 <= result["score"] <= 1.0
    assert len(result["question_ids"]) == 2
    assert result["per_tag_scores"]
    # answers themselves are not exposed on the list payload
    assert "correct_key" not in str(app)


@pytest.mark.usefixtures("migrated_db", "seeded_bank", "bucket", "multi_mode")
async def test_admin_reviews_quiz_answers_with_integrity(client: AsyncClient) -> None:
    from sqlalchemy import update
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from sqlalchemy.pool import NullPool

    from app.models import Job

    creds = {
        "email": f"admin-{uuid4().hex[:8]}@ganek-ci.dev",
        "password": "a-long-secure-password",
    }
    name = f"Review Co {uuid4().hex[:6]}"
    assert (
        await client.post("/api/v1/auth/register", json={"company_name": name, **creds})
    ).status_code == 201
    slug = name.lower().replace(" ", "-")
    job = (await client.post("/api/v1/jobs", json={"title": "Py Dev", "tags": ["python"]})).json()
    engine = create_async_engine(settings.database_url, poolclass=NullPool)
    async with async_sessionmaker(engine)() as db:
        await db.execute(
            update(Job)
            .where(Job.id == job["id"])
            .values(quiz_config={"enabled": True, "tags": ["python"], "question_count": 2})
        )
        await db.commit()
    await engine.dispose()
    assert (await client.post(f"/api/v1/jobs/{job['id']}/publish")).status_code == 200
    await client.post("/api/v1/auth/logout")

    base = f"/api/v1/public/companies/{slug}/jobs/{job['slug']}"
    ticket = (await client.post(f"{base}/apply/upload-url")).json()
    async with httpx.AsyncClient() as raw:
        assert (
            await raw.put(
                ticket["upload_url"],
                content=PDF_BYTES,
                headers={"Content-Type": ticket["content_type"]},
            )
        ).status_code == 200
    resp = await client.post(
        f"{base}/apply",
        json={
            "name": "Jane",
            "email": f"jane-{uuid4().hex[:8]}@ganek-ci.dev",
            "cv_object_key": ticket["object_key"],
            "cv_filename": "cv.pdf",
        },
    )
    token = resp.json()["quiz_token"]
    flagged_question: str | None = None
    while True:
        body = (await client.post(f"/api/v1/public/quiz/{token}/next")).json()
        if body["done"]:
            break
        question = body["question"]
        if flagged_question is None:
            flagged_question = question["id"]
            await client.post(
                f"/api/v1/public/quiz/{token}/events",
                json={
                    "events": [{"type": "blur", "duration_ms": 5000, "question_id": question["id"]}]
                },
            )
        await client.post(
            f"/api/v1/public/quiz/{token}/answer",
            json={"question_id": question["id"], "answer_key": question["options"][0]["key"]},
        )

    assert (await client.post("/api/v1/auth/login", json=creds)).status_code == 200
    application = (await client.get("/api/v1/applications")).json()["items"][0]

    # the completed attempt carries structured, explained flags
    flags = application["quiz_attempt"]["integrity"]["flags"]
    assert flags, "expected an integrity flag from the tab-switch"
    tab_flag = next(f for f in flags if f["code"] == "tab_hidden")
    assert tab_flag["detail"]  # human-readable reasoning
    assert "Q1" in tab_flag["detail"]  # attributed to a question position

    resp = await client.get(f"/api/v1/applications/{application['id']}/quiz-answers")
    assert resp.status_code == 200, resp.text
    reviews = resp.json()
    assert len(reviews) == 2
    for review in reviews:
        assert review["correct_key"] in review["options"]
        assert review["answer_key"] in review["options"]
        assert review["is_correct"] == (review["answer_key"] == review["correct_key"])
        assert review["response_ms"] is not None and review["response_ms"] >= 0
        expected = (
            [{"type": "blur", "duration_ms": 5000}]
            if review["question_id"] == flagged_question
            else []
        )
        assert review["integrity_events"] == expected

    # no quiz / foreign tenant → 404
    await client.post("/api/v1/auth/logout")
    assert (
        await client.post(
            "/api/v1/auth/register",
            json={
                "company_name": f"Nosy Co {uuid4().hex[:6]}",
                "email": f"nosy-{uuid4().hex[:8]}@ganek-ci.dev",
                "password": "a-long-secure-password",
            },
        )
    ).status_code == 201
    assert (
        await client.get(f"/api/v1/applications/{application['id']}/quiz-answers")
    ).status_code == 404


@pytest.mark.usefixtures("migrated_db", "bucket", "multi_mode")
async def test_stage_change_emails_candidate_only_when_asked(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.services import email as email_service

    advances: list[dict[str, object]] = []
    rejections: list[dict[str, object]] = []
    monkeypatch.setattr(email_service, "send_stage_advance", lambda **kw: advances.append(kw))
    monkeypatch.setattr(email_service, "send_rejection", lambda **kw: rejections.append(kw))

    _, email = await _company_with_applicant(client)
    app = (await client.get("/api/v1/applications")).json()["items"][0]
    url = f"/api/v1/applications/{app['id']}/stage"

    # default stays silent
    assert (await client.patch(url, json={"stage": "screening"})).status_code == 200
    assert advances == [] and rejections == []

    # advance with notify → 22a with candidate + branding context
    resp = await client.patch(url, json={"stage": "interview", "notify_candidate": True})
    assert resp.status_code == 200
    assert len(advances) == 1
    assert advances[0]["to"] == email
    assert advances[0]["candidate_name"] == "Jane Applicant"
    assert advances[0]["job_title"] == "Backend Engineer"
    assert "/application/" in str(advances[0]["status_url"])

    # reject with notify → 22b; no completed assessment on this application
    resp = await client.patch(url, json={"stage": "rejected", "notify_candidate": True})
    assert resp.status_code == 200
    assert len(rejections) == 1
    assert rejections[0]["to"] == email
    assert rejections[0]["completed_assessment"] is False
    assert "/c/hire-co-" in str(rejections[0]["careers_url"])  # multi-mode careers page

    # notify on a stage without a template (e.g. screening) is a no-op
    resp = await client.patch(url, json={"stage": "screening", "notify_candidate": True})
    assert resp.status_code == 200
    assert len(advances) == 1 and len(rejections) == 1

    # re-picking the CURRENT stage never re-sends — parity with bulk-reject,
    # which silently skips already-rejected rows (M5.7 H5 ledger item)
    resp = await client.patch(url, json={"stage": "rejected", "notify_candidate": True})
    assert resp.status_code == 200
    assert len(rejections) == 2
    resp = await client.patch(url, json={"stage": "rejected", "notify_candidate": True})
    assert resp.status_code == 200
    assert len(rejections) == 2


@pytest.mark.usefixtures("migrated_db", "seeded_bank", "bucket", "multi_mode")
async def test_remind_sends_reminder_for_pending_attempt(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.services import email as email_service

    reminders: list[dict[str, object]] = []
    monkeypatch.setattr(email_service, "send_quiz_reminder", lambda **kw: reminders.append(kw))

    _, email = await _company_with_applicant(client, with_quiz=True)
    app = (await client.get("/api/v1/applications")).json()["items"][0]

    resp = await client.post(f"/api/v1/applications/{app['id']}/remind")
    assert resp.status_code == 200, resp.text
    assert len(reminders) == 1
    assert reminders[0]["to"] == email
    assert "/quiz/" in str(reminders[0]["quiz_url"])
    assert isinstance(reminders[0]["days_left"], int)

    # reminding again is allowed (recruiter's call how often)
    assert (await client.post(f"/api/v1/applications/{app['id']}/remind")).status_code == 200
    assert len(reminders) == 2


@pytest.mark.usefixtures("migrated_db", "bucket", "multi_mode")
async def test_remind_409s_without_pending_attempt(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.services import email as email_service

    reminders: list[dict[str, object]] = []
    monkeypatch.setattr(email_service, "send_quiz_reminder", lambda **kw: reminders.append(kw))

    await _company_with_applicant(client)  # job without assessment → no attempt
    app = (await client.get("/api/v1/applications")).json()["items"][0]

    resp = await client.post(f"/api/v1/applications/{app['id']}/remind")
    assert resp.status_code == 409
    assert reminders == []


@pytest.mark.usefixtures("migrated_db", "bucket", "multi_mode")
async def test_list_paginates_and_counts_stages(client: AsyncClient) -> None:
    """M5.7 H4: limit/offset windows plus whole-set stage counts — the old
    endpoint materialized every row per visit."""
    creds = {
        "email": f"admin-{uuid4().hex[:8]}@ganek-ci.dev",
        "password": "a-long-secure-password",
    }
    name = f"Page Co {uuid4().hex[:6]}"
    assert (
        await client.post("/api/v1/auth/register", json={"company_name": name, **creds})
    ).status_code == 201
    slug = name.lower().replace(" ", "-")
    job = (await client.post("/api/v1/jobs", json={"title": "Role"})).json()
    assert (await client.post(f"/api/v1/jobs/{job['id']}/publish")).status_code == 200
    await client.post("/api/v1/auth/logout")

    base = f"/api/v1/public/companies/{slug}/jobs/{job['slug']}"
    for i in range(3):
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
                "name": f"Candidate {i}",
                "email": f"cand-{i}-{uuid4().hex[:8]}@ganek-ci.dev",
                "cv_object_key": ticket["object_key"],
                "cv_filename": f"cv-{i}.pdf",
            },
        )
        assert resp.status_code == 201, resp.text
    assert (await client.post("/api/v1/auth/login", json=creds)).status_code == 200

    first = (await client.get("/api/v1/applications?limit=2")).json()
    assert first["total"] == 3
    assert len(first["items"]) == 2
    assert first["stage_counts"] == {"new": 3}

    second = (await client.get("/api/v1/applications?limit=2&offset=2")).json()
    assert len(second["items"]) == 1
    ids = {row["id"] for row in first["items"]} | {row["id"] for row in second["items"]}
    assert len(ids) == 3  # windows are disjoint and cover everything

    # advance one; a stage-filtered page narrows items but NOT the pill counts
    target = first["items"][0]["id"]
    assert (
        await client.patch(f"/api/v1/applications/{target}/stage", json={"stage": "screening"})
    ).status_code == 200
    filtered = (await client.get("/api/v1/applications?stage=screening")).json()
    assert filtered["total"] == 1
    assert [row["id"] for row in filtered["items"]] == [target]
    assert filtered["stage_counts"] == {"new": 2, "screening": 1}

    # the limit is capped server-side
    assert (await client.get("/api/v1/applications?limit=5000")).status_code == 422
