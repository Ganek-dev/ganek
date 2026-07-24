"""M6 recruiter controls: pool filters, timer config, bank browsing, preview, stats."""

import random
from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models import (
    Application,
    Candidate,
    Company,
    Job,
    JobStatus,
)
from app.services import quiz
from app.services import stats as stats_service
from app.services.seed import questions_dir, seed_questions
from tests.db import database_reachable

pytestmark = pytest.mark.skipif(
    not database_reachable(), reason="database not reachable (start postgres or use CI)"
)


@pytest.fixture
def multi_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "mode", "multi")


async def _register(client: AsyncClient) -> None:
    resp = await client.post(
        "/api/v1/auth/register",
        json={
            "company_name": f"RCo {uuid4().hex[:6]}",
            "email": f"admin-{uuid4().hex[:8]}@vetd-ci.dev",
            "password": "a-long-secure-password",
        },
    )
    assert resp.status_code == 201, resp.text


async def _engine_fixture(db: AsyncSession, quiz_config: dict) -> tuple[Company, Job, Application]:
    directory = questions_dir()
    assert directory is not None
    await seed_questions(db, directory)

    company = Company(slug=f"ctrlco-{uuid4().hex[:8]}", name="Ctrl Co")
    db.add(company)
    await db.flush()
    job = Job(
        company_id=company.id,
        slug="py-dev",
        title="Python Dev",
        tags=["python"],
        quiz_config=quiz_config,
    )
    candidate = Candidate(
        company_id=company.id, email=f"c-{uuid4().hex[:8]}@vetd-ci.dev", name="Jane"
    )
    db.add_all([job, candidate])
    await db.flush()
    application = Application(
        company_id=company.id,
        job_id=job.id,
        candidate_id=candidate.id,
        cv_object_key=f"cvs/{company.id}/{uuid4().hex}.pdf",
        cv_filename="cv.pdf",
        cv_size=1000,
    )
    db.add(application)
    await db.commit()
    return company, job, application


# ---------------------------------------------------------------- engine


@pytest.mark.usefixtures("migrated_db")
async def test_pool_honors_difficulty_excludes_and_blocklist(db_session: AsyncSession) -> None:
    company, job, _ = await _engine_fixture(
        db_session,
        {"enabled": True, "tags": ["python"], "difficulties": ["easy"]},  # legacy band -> 1,2
    )
    config = quiz.parse_quiz_config(job)
    pool = await quiz._question_pool(db_session, company, config)
    assert pool, "bank should have easy python questions"
    assert all(q.difficulty <= 2 for q in pool)  # legacy "easy" maps to levels 1-2

    # per-job exclusion removes exactly that question
    target = pool[0].id
    job.quiz_config = {
        "enabled": True,
        "tags": ["python"],
        "difficulties": ["easy"],
        "exclude_ids": [target],
    }
    pool2 = await quiz._question_pool(db_session, company, quiz.parse_quiz_config(job))
    assert target not in {q.id for q in pool2}
    assert {q.id for q in pool2} == {q.id for q in pool} - {target}

    # company-wide blocklist removes it too, without per-job config
    job.quiz_config = {
        "enabled": True,
        "tags": ["python"],
        "difficulties": ["easy"],
    }  # legacy band -> 1,2
    company.blocked_question_ids = [target]
    await db_session.commit()
    pool3 = await quiz._question_pool(db_session, company, quiz.parse_quiz_config(job))
    assert target not in {q.id for q in pool3}


@pytest.mark.usefixtures("migrated_db")
async def test_attempt_freezes_time_limit_and_serve_uses_it(db_session: AsyncSession) -> None:
    company, job, application = await _engine_fixture(
        db_session,
        {"enabled": True, "tags": ["python"], "question_count": 2, "time_limit_seconds": 30},
    )
    attempt = await quiz.create_attempt(db_session, company, application, job, rng=random.Random(7))
    assert attempt is not None
    assert attempt.time_limit_seconds == 30

    served = await quiz.current_or_next_question(db_session, attempt)
    assert served is not None
    answer, _question = served
    window = (answer.deadline_at - answer.served_at).total_seconds()
    assert window == 30 + settings.quiz_network_grace_seconds


@pytest.mark.usefixtures("migrated_db")
async def test_null_time_limit_falls_back_to_question(db_session: AsyncSession) -> None:
    company, job, application = await _engine_fixture(
        db_session,
        {"enabled": True, "tags": ["python"], "question_count": 1, "time_limit_seconds": None},
    )
    attempt = await quiz.create_attempt(db_session, company, application, job, rng=random.Random(7))
    assert attempt is not None
    assert attempt.time_limit_seconds is None

    served = await quiz.current_or_next_question(db_session, attempt)
    assert served is not None
    answer, question = served
    window = (answer.deadline_at - answer.served_at).total_seconds()
    assert window == question.time_limit_seconds + settings.quiz_network_grace_seconds


# ---------------------------------------------------------------- bank API


@pytest.mark.usefixtures("migrated_db", "seeded_bank", "multi_mode")
async def test_bank_browse_filters_and_tenancy(client: AsyncClient) -> None:
    await _register(client)

    page = (await client.get("/api/v1/questions/bank")).json()
    assert page["total"] > 100
    assert page["tags"], "distinct tag list must be populated"
    assert all(item["correct_key"] in "abcd" for item in page["items"])

    filtered = (await client.get("/api/v1/questions/bank?tag=python&difficulty=2")).json()
    assert filtered["total"] > 0
    assert all("python" in item["tags"] for item in filtered["items"])
    assert all(item["difficulty"] == 2 for item in filtered["items"])

    # company-private questions never surface in the bank
    marker = f"Zzq{uuid4().hex[:10]}"
    resp = await client.post(
        "/api/v1/questions",
        json={
            "prompt_md": f"Private question {marker} about our stack?",
            "options": {"a": "1", "b": "2", "c": "3", "d": "4"},
            "correct_key": "a",
            "tags": ["python"],
            "difficulty": 2,
        },
    )
    assert resp.status_code == 201, resp.text
    hits = (await client.get(f"/api/v1/questions/bank?q={marker}")).json()
    assert hits["total"] == 0


@pytest.mark.usefixtures("migrated_db", "seeded_bank", "multi_mode")
async def test_bank_block_roundtrip_and_member_forbidden(client: AsyncClient) -> None:
    await _register(client)
    first = (await client.get("/api/v1/questions/bank?limit=1")).json()["items"][0]

    assert (await client.put(f"/api/v1/questions/bank/{first['id']}/block")).status_code == 204
    # ordering is deterministic (by id), so the same question comes back first
    refetched = (await client.get("/api/v1/questions/bank?limit=1")).json()["items"][0]
    assert refetched["id"] == first["id"] and refetched["blocked"] is True

    assert (await client.delete(f"/api/v1/questions/bank/{first['id']}/block")).status_code == 204
    assert (await client.put("/api/v1/questions/bank/nope-404/block")).status_code == 404

    # members can browse but not block
    member_email = f"member-{uuid4().hex[:8]}@vetd-ci.dev"
    resp = await client.post(
        "/api/v1/users",
        json={"email": member_email, "password": "member-password-1234", "role": "member"},
    )
    assert resp.status_code == 201, resp.text
    await client.post("/api/v1/auth/logout")
    await client.post(
        "/api/v1/auth/login",
        json={"email": member_email, "password": "member-password-1234"},
    )
    assert (await client.get("/api/v1/questions/bank")).status_code == 200
    assert (await client.put(f"/api/v1/questions/bank/{first['id']}/block")).status_code == 403


# ---------------------------------------------------------------- preview API


@pytest.mark.usefixtures("migrated_db", "seeded_bank", "multi_mode")
async def test_quiz_preview_reflects_config(client: AsyncClient) -> None:
    await _register(client)
    job = (
        await client.post(
            "/api/v1/jobs",
            json={
                "title": "Py Dev",
                "tags": ["python"],
                "quiz_config": {
                    "enabled": True,
                    "tags": ["python"],
                    "question_count": 3,
                    "time_limit_seconds": 25,
                    "difficulties": [1, 2, 3],
                },
            },
        )
    ).json()

    preview = (await client.get(f"/api/v1/jobs/{job['id']}/quiz-preview")).json()
    assert preview["enabled"] is True
    assert preview["time_limit_seconds"] == 25
    assert preview["eligible_count"] > 0
    assert preview["eligible_by_tag"]["python"] == preview["eligible_count"]
    assert 0 < len(preview["sample_question_ids"]) <= 3
    pool_ids = {q["id"] for q in preview["pool"]}
    assert set(preview["sample_question_ids"]) <= pool_ids
    assert all(q["difficulty"] <= 3 for q in preview["pool"])

    # exclude one pooled question: flag flips, sample avoids it
    excluded_id = preview["pool"][0]["id"]
    patch = await client.patch(
        f"/api/v1/jobs/{job['id']}",
        json={
            "quiz_config": {
                "enabled": True,
                "tags": ["python"],
                "question_count": 3,
                "time_limit_seconds": 25,
                "difficulties": [1, 2, 3],
                "exclude_ids": [excluded_id],
            }
        },
    )
    assert patch.status_code == 200, patch.text
    preview2 = (await client.get(f"/api/v1/jobs/{job['id']}/quiz-preview")).json()
    flags = {q["id"]: q["excluded"] for q in preview2["pool"]}
    assert flags[excluded_id] is True
    assert excluded_id not in preview2["sample_question_ids"]
    assert preview2["eligible_count"] == preview["eligible_count"] - 1


# ---------------------------------------------------------------- stats


@pytest.mark.usefixtures("migrated_db", "multi_mode")
async def test_stats_overview_endpoint_shape(client: AsyncClient) -> None:
    await _register(client)
    resp = await client.get("/api/v1/stats/overview")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["jobs"] == {"draft": 0, "published": 0, "closed": 0}
    assert body["applications"] == {"total": 0, "new": 0, "last_7_days": 0}
    assert body["quiz"]["attempts_total"] == 0
    assert len(body["weekly"]) == 8
    assert body["per_job"] == [] and body["recent"] == []


@pytest.mark.usefixtures("migrated_db")
async def test_stats_aggregates_are_tenant_scoped(db_session: AsyncSession) -> None:
    company, job, application = await _engine_fixture(
        db_session, {"enabled": False, "tags": ["python"]}
    )
    job.status = JobStatus.PUBLISHED
    other = Company(slug=f"other-{uuid4().hex[:8]}", name="Other Co")
    db_session.add(other)
    await db_session.flush()
    db_session.add(Job(company_id=other.id, slug="x", title="X", tags=[]))
    await db_session.commit()

    overview = await stats_service.overview(db_session, company)
    assert overview.jobs.published == 1 and overview.jobs.draft == 0
    assert overview.applications.total == 1
    assert overview.applications.new == 1
    assert overview.applications.last_7_days == 1
    assert sum(point.count for point in overview.weekly) == 1
    assert [p.job_id for p in overview.per_job] == [job.id]
    assert overview.per_job[0].applications == 1
    assert overview.recent[0].id == application.id
    assert overview.recent[0].candidate_name == "Jane"

    other_view = await stats_service.overview(db_session, other)
    assert other_view.applications.total == 0
    assert len(other_view.per_job) == 1  # only its own draft job
    assert other_view.jobs.draft == 1
