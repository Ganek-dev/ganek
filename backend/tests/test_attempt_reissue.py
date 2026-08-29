"""Invalidate & re-invite (D6 integrity v2): multi-attempt reissue + flag review."""

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import httpx
import pytest
from httpx import AsyncClient
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models import QuizAttempt
from app.services import email as email_service
from tests.db import database_reachable, s3_reachable

pytestmark = pytest.mark.skipif(
    not (database_reachable() and s3_reachable()),
    reason="database and object storage required (start postgres+minio or use CI)",
)

PDF_BYTES = b"%PDF-1.4 reissue flow"


@pytest.fixture
def multi_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "mode", "multi")


async def _register_admin(client: AsyncClient) -> tuple[dict[str, str], str]:
    """Register a fresh company; returns (admin creds, slug), still logged in."""
    creds = {
        "email": f"admin-{uuid4().hex[:8]}@ganek-ci.dev",
        "password": "a-long-secure-password",
    }
    name = f"Reissue Co {uuid4().hex[:6]}"
    resp = await client.post("/api/v1/auth/register", json={"company_name": name, **creds})
    assert resp.status_code == 201, resp.text
    return creds, name.lower().replace(" ", "-")


async def _publish_job_and_apply(
    client: AsyncClient, slug: str, job_payload: dict[str, object]
) -> dict[str, str | None]:
    """Create+publish the job as the logged-in admin, log out, apply as a
    candidate; returns the apply response json."""
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
    resp = await client.post(
        f"{base}/apply",
        json={
            "name": "Tomas Hruby",
            "email": f"tomas-{uuid4().hex[:8]}@ganek-ci.dev",
            "cv_object_key": ticket["object_key"],
            "cv_filename": "tomas-cv.pdf",
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _apply_with_quiz(
    client: AsyncClient, *, with_quiz: bool = True
) -> tuple[dict[str, str | None], dict[str, str]]:
    """Register + publish (+quiz) + apply; returns (apply json, admin creds)."""
    creds, slug = await _register_admin(client)
    job_payload: dict[str, object] = {"title": "Backend Engineer"}
    if with_quiz:
        job_payload["tags"] = ["python"]
        job_payload["quiz_config"] = {"enabled": True, "question_count": 2}
    return await _publish_job_and_apply(client, slug, job_payload), creds


async def _login_and_get_application(
    client: AsyncClient, creds: dict[str, str]
) -> dict[str, object]:
    assert (await client.post("/api/v1/auth/login", json=creds)).status_code == 200
    applications = (await client.get("/api/v1/applications")).json()["items"]
    assert len(applications) == 1
    return applications[0]


@pytest.mark.usefixtures("migrated_db", "seeded_bank", "bucket", "multi_mode")
async def test_reissue_supersedes_attempt_with_fresh_questions(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    sent: list[dict[str, object]] = []
    monkeypatch.setattr(email_service, "send_quiz_invite", lambda **kwargs: sent.append(kwargs))
    applied, creds = await _apply_with_quiz(client)
    old_token = applied["quiz_token"]
    assert old_token is not None
    old_state = (await client.get(f"/api/v1/public/quiz/{old_token}")).json()
    sent.clear()  # drop the apply-time invite (17a); watch only the reissue

    application = await _login_and_get_application(client, creds)
    old_ids = set(application["quiz_attempt"]["question_ids"])
    assert application["quiz_attempt"]["status"] == "pending"

    resp = await client.post(f"/api/v1/applications/{application['id']}/quiz/reissue")
    assert resp.status_code == 200, resp.text
    new_attempt = resp.json()
    assert new_attempt["status"] == "pending"
    new_ids = set(new_attempt["question_ids"])
    assert len(new_ids) == len(old_ids)
    # the python pool is far larger than 2×2 — fresh selection avoids repeats
    assert not (new_ids & old_ids)
    reissue = new_attempt["integrity"]["reissue"]
    assert reissue["reason"] == "integrity"
    assert reissue["mode"] == "manual"
    assert reissue["by_user_id"] is not None

    # the fresh invite email went to the candidate with a working link
    assert len(sent) == 1 and "/quiz/" in str(sent[0]["quiz_url"])

    # admin detail now shows the fresh attempt as THE attempt
    detail = (await client.get(f"/api/v1/applications/{application['id']}")).json()
    assert set(detail["quiz_attempt"]["question_ids"]) == new_ids

    # the superseded link is dead: state says invalidated, play is 410
    old_state_after = (await client.get(f"/api/v1/public/quiz/{old_token}")).json()
    assert old_state["status"] == "pending"
    assert old_state_after["status"] == "invalidated"
    assert (await client.post(f"/api/v1/public/quiz/{old_token}/next")).status_code == 410


@pytest.mark.usefixtures("migrated_db", "seeded_bank", "bucket", "multi_mode")
async def test_dismiss_flags_records_review(client: AsyncClient) -> None:
    _, creds = await _apply_with_quiz(client)
    application = await _login_and_get_application(client, creds)

    resp = await client.post(f"/api/v1/applications/{application['id']}/quiz/dismiss-flags")
    assert resp.status_code == 200, resp.text
    review = resp.json()["integrity"]["review"]
    assert review["decision"] == "dismissed"
    assert review["by_user_id"] is not None


@pytest.mark.usefixtures("migrated_db", "bucket", "multi_mode")
async def test_reissue_without_assessment_conflicts(client: AsyncClient) -> None:
    _, creds = await _apply_with_quiz(client, with_quiz=False)
    application = await _login_and_get_application(client, creds)
    for action in ("reissue", "dismiss-flags"):
        resp = await client.post(f"/api/v1/applications/{application['id']}/quiz/{action}")
        assert resp.status_code == 409, action


@pytest.mark.usefixtures("migrated_db", "seeded_bank", "bucket", "multi_mode")
async def test_reissue_is_tenant_scoped(client: AsyncClient) -> None:
    applied, _ = await _apply_with_quiz(client)
    assert applied["quiz_token"] is not None

    # a different company's admin can't touch the application
    other = {
        "email": f"admin-{uuid4().hex[:8]}@ganek-ci.dev",
        "password": "a-long-secure-password",
    }
    resp = await client.post(
        "/api/v1/auth/register", json={"company_name": f"Other Co {uuid4().hex[:6]}", **other}
    )
    assert resp.status_code == 201
    foreign_id = uuid4()
    assert (await client.post(f"/api/v1/applications/{foreign_id}/quiz/reissue")).status_code == 404


async def _expire_attempts(db_session: AsyncSession, application_id: str) -> None:
    await db_session.execute(
        update(QuizAttempt)
        .where(QuizAttempt.application_id == UUID(application_id))
        .values(expires_at=datetime.now(UTC) - timedelta(hours=1))
    )
    await db_session.commit()


@pytest.mark.usefixtures("migrated_db", "seeded_bank", "bucket", "multi_mode")
async def test_expired_request_manual_records_for_the_team(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    applied, creds = await _apply_with_quiz(client)
    token = applied["quiz_token"]
    application = await _login_and_get_application(client, creds)
    await client.post("/api/v1/auth/logout")
    await _expire_attempts(db_session, str(application["id"]))

    # an active link refuses the request; an expired one records it
    resp = await client.post(f"/api/v1/public/quiz/{token}/request-reissue")
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"reissued": False}
    # idempotent-ish: repeats just bump the count
    assert (await client.post(f"/api/v1/public/quiz/{token}/request-reissue")).json() == {
        "reissued": False
    }

    assert (await client.post("/api/v1/auth/login", json=creds)).status_code == 200
    detail = (await client.get(f"/api/v1/applications/{application['id']}")).json()
    requested = detail["quiz_attempt"]["integrity"]["reissue_requested"]
    assert requested["count"] == 2 and requested["at"]


@pytest.mark.usefixtures("migrated_db", "seeded_bank", "bucket", "multi_mode")
async def test_expired_request_auto_reissues_once(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    sent: list[dict[str, object]] = []
    monkeypatch.setattr(email_service, "send_quiz_invite", lambda **kwargs: sent.append(kwargs))
    applied, creds = await _apply_with_quiz(client)
    token = applied["quiz_token"]
    application = await _login_and_get_application(client, creds)
    resp = await client.patch("/api/v1/company/settings", json={"quiz_expired_reissue": "auto"})
    assert resp.status_code == 200, resp.text
    assert resp.json()["settings"] == {"quiz_expired_reissue": "auto"}
    await client.post("/api/v1/auth/logout")
    await _expire_attempts(db_session, str(application["id"]))
    sent.clear()

    resp = await client.post(f"/api/v1/public/quiz/{token}/request-reissue")
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"reissued": True}
    # delivery is email-only: a fresh working link went to the candidate
    assert len(sent) == 1
    new_token = str(sent[0]["quiz_url"]).rsplit("/quiz/", 1)[1]
    assert (await client.get(f"/api/v1/public/quiz/{new_token}")).json()["status"] == "pending"

    # the old link now reports a re-issued state
    assert (await client.post(f"/api/v1/public/quiz/{token}/request-reissue")).status_code == 409

    # auto works ONCE: expire the fresh attempt too → falls back to manual
    await _expire_attempts(db_session, str(application["id"]))
    resp = await client.post(f"/api/v1/public/quiz/{new_token}/request-reissue")
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"reissued": False}

    # the lateness is visible on the fresh attempt's audit trail
    assert (await client.post("/api/v1/auth/login", json=creds)).status_code == 200
    detail = (await client.get(f"/api/v1/applications/{application['id']}")).json()
    reissue = detail["quiz_attempt"]["integrity"]["reissue"]
    assert reissue["reason"] == "expired" and reissue["mode"] == "auto"
    assert reissue["by_user_id"] is None


@pytest.mark.usefixtures("migrated_db", "seeded_bank", "bucket", "multi_mode")
async def test_active_link_refuses_reissue_request(client: AsyncClient) -> None:
    applied, _ = await _apply_with_quiz(client)
    resp = await client.post(f"/api/v1/public/quiz/{applied['quiz_token']}/request-reissue")
    assert resp.status_code == 409


@pytest.mark.usefixtures("migrated_db", "multi_mode")
async def test_settings_patch_is_admin_only_and_validated(client: AsyncClient) -> None:
    creds = {
        "email": f"admin-{uuid4().hex[:8]}@ganek-ci.dev",
        "password": "a-long-secure-password",
    }
    resp = await client.post(
        "/api/v1/auth/register", json={"company_name": f"Set Co {uuid4().hex[:6]}", **creds}
    )
    assert resp.status_code == 201
    assert (
        await client.patch("/api/v1/company/settings", json={"quiz_expired_reissue": "always"})
    ).status_code == 422
    # null resets to the default
    assert (
        await client.patch("/api/v1/company/settings", json={"quiz_expired_reissue": "auto"})
    ).json()["settings"] == {"quiz_expired_reissue": "auto"}
    assert (
        await client.patch("/api/v1/company/settings", json={"quiz_expired_reissue": None})
    ).json()["settings"] == {}

    member_email = f"member-{uuid4().hex[:8]}@ganek-ci.dev"
    member_pw = "member-password-1234"
    resp = await client.post(
        "/api/v1/users", json={"email": member_email, "password": member_pw, "role": "member"}
    )
    assert resp.status_code == 201
    await client.post("/api/v1/auth/logout")
    assert (
        await client.post("/api/v1/auth/login", json={"email": member_email, "password": member_pw})
    ).status_code == 200
    assert (
        await client.patch("/api/v1/company/settings", json={"quiz_expired_reissue": "auto"})
    ).status_code == 403


@pytest.mark.usefixtures("migrated_db", "seeded_bank", "bucket", "multi_mode")
async def test_quiz_answers_review_survives_reissue(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Regression: the recruiter answers/integrity review must read the LATEST
    attempt — with 1..N rows per application (0012), scalar_one_or_none()
    raised MultipleResultsFound (a 500) for every re-issued applicant."""
    sent: list[dict[str, object]] = []
    monkeypatch.setattr(email_service, "send_quiz_invite", lambda **kwargs: sent.append(kwargs))
    applied, creds = await _apply_with_quiz(client)
    old_token = applied["quiz_token"]
    assert old_token is not None
    served = (await client.post(f"/api/v1/public/quiz/{old_token}/next")).json()["question"]
    resp = await client.post(
        f"/api/v1/public/quiz/{old_token}/answer",
        json={"question_id": served["id"], "answer_key": served["options"][0]["key"]},
    )
    assert resp.status_code == 200, resp.text
    sent.clear()  # watch only the re-issue invite from here

    application = await _login_and_get_application(client, creds)
    resp = await client.post(f"/api/v1/applications/{application['id']}/quiz/reissue")
    assert resp.status_code == 200, resp.text

    # fresh attempt, nothing answered yet: an empty review, not a 500
    resp = await client.get(f"/api/v1/applications/{application['id']}/quiz-answers")
    assert resp.status_code == 200, resp.text
    assert resp.json() == []

    # answering on the NEW link shows up in the review
    new_token = str(sent[0]["quiz_url"]).rsplit("/", 1)[-1]
    served = (await client.post(f"/api/v1/public/quiz/{new_token}/next")).json()["question"]
    resp = await client.post(
        f"/api/v1/public/quiz/{new_token}/answer",
        json={"question_id": served["id"], "answer_key": served["options"][0]["key"]},
    )
    assert resp.status_code == 200, resp.text
    reviews = (await client.get(f"/api/v1/applications/{application['id']}/quiz-answers")).json()
    assert [r["question_id"] for r in reviews] == [served["id"]]


@pytest.mark.usefixtures("migrated_db", "seeded_bank", "bucket", "multi_mode")
async def test_reissue_tops_up_from_history_when_fresh_pool_runs_dry(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A tiny pool still yields a full re-issue: fresh questions are preferred,
    the rest topped up from already-served ones (the dry-pool branch)."""
    monkeypatch.setattr(email_service, "send_quiz_invite", lambda **kwargs: None)
    creds, slug = await _register_admin(client)
    pool_ids: list[str] = []
    for n in range(3):
        resp = await client.post(
            "/api/v1/questions",
            json={
                "prompt_md": f"Tiny-pool question number {n}?",
                "options": {"a": "Yes", "b": "No", "c": "Maybe", "d": "Never"},
                "correct_key": "a",
                "tags": ["tinypool"],
                "difficulty": 2,
            },
        )
        assert resp.status_code == 201, resp.text
        pool_ids.append(resp.json()["id"])
    await _publish_job_and_apply(
        client,
        slug,
        {
            "title": "Backend Engineer",
            "tags": ["tinypool"],
            "quiz_config": {"enabled": True, "question_count": 2},
        },
    )

    application = await _login_and_get_application(client, creds)
    old_ids = set(application["quiz_attempt"]["question_ids"])
    assert old_ids < set(pool_ids) and len(old_ids) == 2
    (unseen_id,) = set(pool_ids) - old_ids

    resp = await client.post(f"/api/v1/applications/{application['id']}/quiz/reissue")
    assert resp.status_code == 200, resp.text
    new_ids = resp.json()["question_ids"]
    assert len(new_ids) == 2 == len(set(new_ids))
    assert unseen_id in new_ids  # the one fresh question is always used
    assert len(set(new_ids) & old_ids) == 1  # topped up from history, not short-served


@pytest.mark.usefixtures("migrated_db", "seeded_bank", "bucket", "multi_mode")
async def test_reissue_reserves_curated_questionnaire_set(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Questionnaire-attached jobs re-serve the curated set in curated order —
    the set IS the quiz (the questionnaire branch of re-issue)."""
    monkeypatch.setattr(email_service, "send_quiz_invite", lambda **kwargs: None)
    creds, slug = await _register_admin(client)
    refs = ["py-mutable-default-1", "py-gil-1", "py-dict-ordering-1"]
    created = await client.post(
        "/api/v1/questionnaires",
        json={"name": "Reissue set", "question_refs": refs, "shuffle": False},
    )
    assert created.status_code == 201, created.text
    await _publish_job_and_apply(
        client,
        slug,
        {
            "title": "Backend Engineer",
            "quiz_config": {"enabled": True, "questionnaire_id": created.json()["id"]},
        },
    )

    application = await _login_and_get_application(client, creds)
    assert application["quiz_attempt"]["question_ids"] == refs

    resp = await client.post(f"/api/v1/applications/{application['id']}/quiz/reissue")
    assert resp.status_code == 200, resp.text
    fresh = resp.json()
    assert fresh["question_ids"] == refs  # same set, same curated order
    assert fresh["integrity"]["reissue"]["reason"] == "integrity"
