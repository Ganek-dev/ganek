"""Candidate-side extra-time request (quiz intro, "Need more time?"): the
request goes to the team first, shows up in the recruiter queue, and the
existing extra-time grant resolves it."""

from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.security import read_quiz_token
from app.models import QuizAttempt
from app.services import email as email_service
from tests.db import database_reachable, s3_reachable
from tests.test_attempt_reissue import _apply_with_quiz, _login_and_get_application

pytestmark = pytest.mark.skipif(
    not (database_reachable() and s3_reachable()),
    reason="database and object storage required (start postgres+minio or use CI)",
)


@pytest.fixture
def multi_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "mode", "multi")


async def _queue_keys(client: AsyncClient) -> list[str]:
    resp = await client.get("/api/v1/stats/queue")
    assert resp.status_code == 200, resp.text
    return [item["key"] for item in resp.json()["items"] if item["kind"] == "extra-time"]


@pytest.mark.usefixtures("migrated_db", "seeded_bank", "bucket", "multi_mode")
async def test_request_reaches_the_queue_and_a_grant_resolves_it(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    sent: list[dict[str, object]] = []
    monkeypatch.setattr(email_service, "send_quiz_invite", lambda **kwargs: sent.append(kwargs))
    applied, creds = await _apply_with_quiz(client)
    token = applied["quiz_token"]
    assert token is not None

    state = (await client.get(f"/api/v1/public/quiz/{token}")).json()
    assert state["can_request_extra_time"] is True
    assert state["extra_time_requested"] is False

    resp = await client.post(f"/api/v1/public/quiz/{token}/request-extra-time")
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"requested": True}
    # a second click is harmless: the count goes up, nothing else
    assert (await client.post(f"/api/v1/public/quiz/{token}/request-extra-time")).status_code == 200
    state = (await client.get(f"/api/v1/public/quiz/{token}")).json()
    assert state["extra_time_requested"] is True
    assert "time_multiplier" not in state

    application = await _login_and_get_application(client, creds)
    request = application["quiz_attempt"]["integrity"]["extra_time_requested"]
    assert request["count"] == 2
    assert request["at"]
    assert set(request) == {"at", "count"}  # no reason is ever stored
    keys = await _queue_keys(client)
    assert len(keys) == 1 and keys[0].startswith("extra-time:")

    sent.clear()
    resp = await client.post(
        f"/api/v1/applications/{application['id']}/quiz/extra-time",
        json={"time_multiplier": 1.5},
    )
    assert resp.status_code == 200, resp.text
    assert len(sent) == 1  # the invite goes out again with the new timing, as today
    assert await _queue_keys(client) == []

    await client.post("/api/v1/auth/logout")
    state = (await client.get(f"/api/v1/public/quiz/{token}")).json()
    assert state["can_request_extra_time"] is False
    resp = await client.post(f"/api/v1/public/quiz/{token}/request-extra-time")
    assert resp.status_code == 409


@pytest.mark.usefixtures("migrated_db", "seeded_bank", "bucket", "multi_mode")
async def test_no_request_once_started_or_expired(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    applied, _ = await _apply_with_quiz(client)
    token = applied["quiz_token"]
    assert (await client.post(f"/api/v1/public/quiz/{token}/next")).json()["done"] is False
    state = (await client.get(f"/api/v1/public/quiz/{token}")).json()
    assert state["can_request_extra_time"] is False
    resp = await client.post(f"/api/v1/public/quiz/{token}/request-extra-time")
    assert resp.status_code == 409
    assert "before the assessment starts" in resp.json()["detail"]

    other, _ = await _apply_with_quiz(client)
    other_id = read_quiz_token(str(other["quiz_token"]))
    assert other_id is not None
    await db_session.execute(
        update(QuizAttempt)
        .where(QuizAttempt.id == other_id)
        .values(expires_at=datetime.now(UTC) - timedelta(minutes=1))
    )
    await db_session.commit()
    resp = await client.post(f"/api/v1/public/quiz/{other['quiz_token']}/request-extra-time")
    assert resp.status_code in (409, 410)
