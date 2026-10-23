"""Extra-time accommodation: a recruiter grants a timed-quiz multiplier
(1.5x or 2x) on request. Timing stays server-side, scoring untouched."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models import AttemptStatus, Question, QuizAttempt
from app.services import email as email_service
from app.services import quiz as quiz_service
from tests.db import database_reachable, s3_reachable
from tests.test_attempt_reissue import _apply_with_quiz, _login_and_get_application

db_required = pytest.mark.skipif(
    not (database_reachable() and s3_reachable()),
    reason="database and object storage required (start postgres+minio or use CI)",
)


@pytest.fixture
def multi_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "mode", "multi")


# --- DB-free ----------------------------------------------------------------


def test_effective_time_limit_scales_with_the_frozen_multiplier() -> None:
    question = Question(time_limit_seconds=20)
    doubled = QuizAttempt(time_limit_seconds=15, time_multiplier=2.0)
    assert quiz_service.effective_time_limit(doubled, question) == 30
    # NULL per-job limit falls back to the question's own, still multiplied
    per_question = QuizAttempt(time_limit_seconds=None, time_multiplier=2.0)
    assert quiz_service.effective_time_limit(per_question, question) == 40
    # time-and-a-half rounds up: nobody loses a half second to arithmetic
    half = QuizAttempt(time_limit_seconds=15, time_multiplier=1.5)
    assert quiz_service.effective_time_limit(half, question) == 23
    plain = QuizAttempt(time_limit_seconds=15, time_multiplier=1.0)
    assert quiz_service.effective_time_limit(plain, question) == 15


def test_seconds_per_question_is_the_multiplied_job_limit_or_none() -> None:
    assert (
        quiz_service.seconds_per_question(QuizAttempt(time_limit_seconds=20, time_multiplier=2.0))
        == 40
    )
    assert (
        quiz_service.seconds_per_question(QuizAttempt(time_limit_seconds=None, time_multiplier=2.0))
        is None
    )


# --- API ---------------------------------------------------------------------


@db_required
@pytest.mark.usefixtures("migrated_db", "seeded_bank", "bucket", "multi_mode")
async def test_grant_on_pending_attempt_applies_in_place_and_resends_invite(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    sent: list[dict[str, object]] = []
    monkeypatch.setattr(email_service, "send_quiz_invite", lambda **kwargs: sent.append(kwargs))
    applied, creds = await _apply_with_quiz(client)
    token = applied["quiz_token"]
    assert token is not None
    assert (await client.get(f"/api/v1/public/quiz/{token}")).json()["seconds_per_question"] == 20
    sent.clear()

    application = await _login_and_get_application(client, creds)
    before = application["quiz_attempt"]
    assert before["status"] == "pending"
    assert before["time_multiplier"] == 1.0

    resp = await client.post(
        f"/api/v1/applications/{application['id']}/quiz/extra-time",
        json={"time_multiplier": 2},
    )
    assert resp.status_code == 200, resp.text
    attempt = resp.json()
    # same attempt, same questions, same link: nothing was re-issued
    assert attempt["status"] == "pending"
    assert attempt["question_ids"] == before["question_ids"]
    assert attempt["time_multiplier"] == 2.0
    assert "reissue" not in attempt["integrity"]
    grant = attempt["integrity"]["accommodation"]
    assert grant["time_multiplier"] == 2.0
    assert grant["by_user_id"] is not None
    assert grant["at"]

    # the candidate got the invite again, with the new timing
    assert len(sent) == 1
    assert sent[0]["seconds_per_question"] == 40
    assert "/quiz/" in str(sent[0]["quiz_url"])

    # candidate surfaces show the multiplied seconds and nothing else new
    await client.post("/api/v1/auth/logout")
    state = (await client.get(f"/api/v1/public/quiz/{token}")).json()
    assert state["seconds_per_question"] == 40
    assert "time_multiplier" not in state
    served = (await client.post(f"/api/v1/public/quiz/{token}/next")).json()
    question = served["question"]
    assert question["time_limit_seconds"] == 40
    assert "correct_key" not in question
    served_at = datetime.now(UTC)
    deadline = datetime.fromisoformat(question["deadline_at"])
    expected = served_at + timedelta(seconds=40 + settings.quiz_network_grace_seconds)
    assert abs((deadline - expected).total_seconds()) < 5


@db_required
@pytest.mark.usefixtures("migrated_db", "seeded_bank", "bucket", "multi_mode")
async def test_grant_on_started_attempt_reissues_with_the_multiplier(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    sent: list[dict[str, object]] = []
    monkeypatch.setattr(email_service, "send_quiz_invite", lambda **kwargs: sent.append(kwargs))
    applied, creds = await _apply_with_quiz(client)
    token = applied["quiz_token"]
    assert token is not None
    # the candidate already started: the first question is on screen
    assert (await client.post(f"/api/v1/public/quiz/{token}/next")).json()["done"] is False
    sent.clear()

    application = await _login_and_get_application(client, creds)
    old = application["quiz_attempt"]
    assert old["status"] == "in_progress"

    resp = await client.post(
        f"/api/v1/applications/{application['id']}/quiz/extra-time",
        json={"time_multiplier": 1.5},
    )
    assert resp.status_code == 200, resp.text
    fresh = resp.json()
    assert fresh["status"] == "pending"
    assert fresh["time_multiplier"] == 1.5
    assert not (set(fresh["question_ids"]) & set(old["question_ids"]))
    assert fresh["integrity"]["reissue"]["reason"] == "accommodation"
    assert fresh["integrity"]["reissue"]["mode"] == "manual"
    assert fresh["integrity"]["accommodation"]["time_multiplier"] == 1.5
    assert len(sent) == 1 and sent[0]["seconds_per_question"] == 30

    # the old link is dead, the superseded row keeps its own multiplier
    assert (await client.get(f"/api/v1/public/quiz/{token}")).json()["status"] == "invalidated"
    assert (await client.post(f"/api/v1/public/quiz/{token}/next")).status_code == 410


@db_required
@pytest.mark.usefixtures("migrated_db", "seeded_bank", "bucket", "multi_mode")
async def test_expired_link_reissue_keeps_the_grant(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(email_service, "send_quiz_invite", lambda **kwargs: None)
    _, creds = await _apply_with_quiz(client)
    application = await _login_and_get_application(client, creds)
    granted = (
        await client.post(
            f"/api/v1/applications/{application['id']}/quiz/extra-time",
            json={"time_multiplier": 2},
        )
    ).json()
    assert granted["time_multiplier"] == 2.0

    # the 24h window closed and the candidate hit the dead link (expired)
    await db_session.execute(
        update(QuizAttempt)
        .where(QuizAttempt.application_id == application["id"])
        .values(status=AttemptStatus.EXPIRED, expires_at=datetime.now(UTC) - timedelta(hours=1))
    )
    await db_session.commit()
    resp = await client.post(f"/api/v1/applications/{application['id']}/quiz/reissue")
    assert resp.status_code == 200, resp.text
    fresh = resp.json()
    assert fresh["integrity"]["reissue"]["reason"] == "expired"
    assert fresh["time_multiplier"] == 2.0
    assert fresh["integrity"]["accommodation"]["time_multiplier"] == 2.0


@db_required
@pytest.mark.usefixtures("migrated_db", "seeded_bank", "bucket", "multi_mode")
async def test_grant_is_admin_only_and_validated(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(email_service, "send_quiz_invite", lambda **kwargs: None)
    _, creds = await _apply_with_quiz(client)
    application = await _login_and_get_application(client, creds)
    url = f"/api/v1/applications/{application['id']}/quiz/extra-time"
    # only 1, 1.5 and 2 exist: no custom multipliers, no "a little more"
    assert (await client.post(url, json={"time_multiplier": 1.75})).status_code == 422
    assert (await client.post(url, json={"time_multiplier": 3})).status_code == 422

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
    assert (await client.post(url, json={"time_multiplier": 2})).status_code == 403


@db_required
@pytest.mark.usefixtures("migrated_db", "seeded_bank", "bucket", "multi_mode")
async def test_grant_of_one_removes_a_pending_accommodation(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    sent: list[dict[str, object]] = []
    monkeypatch.setattr(email_service, "send_quiz_invite", lambda **kwargs: sent.append(kwargs))
    _, creds = await _apply_with_quiz(client)
    application = await _login_and_get_application(client, creds)
    url = f"/api/v1/applications/{application['id']}/quiz/extra-time"
    assert (await client.post(url, json={"time_multiplier": 2})).json()["time_multiplier"] == 2.0
    sent.clear()
    back = (await client.post(url, json={"time_multiplier": 1})).json()
    assert back["time_multiplier"] == 1.0
    assert "accommodation" not in back["integrity"]
    assert len(sent) == 1 and sent[0]["seconds_per_question"] == 20
