"""Applicant timeline (board card "Candidate timeline"): GET
/applications/{id}/timeline merges the activity log, the email outbox and
the quiz attempts into one trail, newest first. One test per event source.
"""

import re
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models import QuizAttempt
from tests.db import database_reachable, s3_reachable
from tests.helpers import upload_pdf

pytestmark = pytest.mark.skipif(
    not (database_reachable() and s3_reachable()),
    reason="database and object storage required (start postgres+minio or use CI)",
)

PDF_BYTES = b"%PDF-1.4 timeline"


@pytest.fixture
def multi_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "mode", "multi")


async def _company(client: AsyncClient, *, quiz: bool) -> tuple[dict[str, str], str]:
    """Registers a company and publishes one job; logged out at the end.
    Returns (admin creds, public job base)."""
    creds = {
        "email": f"admin-{uuid4().hex[:8]}@ganek-ci.dev",
        "password": "a-long-secure-password",
    }
    name = f"Trail Co {uuid4().hex[:6]}"
    resp = await client.post("/api/v1/auth/register", json={"company_name": name, **creds})
    assert resp.status_code == 201, resp.text
    slug = name.lower().replace(" ", "-")
    body: dict[str, object] = {"title": "Backend Engineer"}
    if quiz:
        body |= {"tags": ["python"], "quiz_config": {"enabled": True, "question_count": 2}}
    job = (await client.post("/api/v1/jobs", json=body)).json()
    assert (await client.post(f"/api/v1/jobs/{job['id']}/publish")).status_code == 200
    await client.post("/api/v1/auth/logout")
    return creds, f"/api/v1/public/companies/{slug}/jobs/{job['slug']}"


async def _apply(client: AsyncClient, base: str) -> dict[str, str | None]:
    ticket = (await client.post(f"{base}/apply/upload-url")).json()
    assert (await upload_pdf(ticket, PDF_BYTES)).is_success
    resp = await client.post(
        f"{base}/apply",
        json={
            "name": "Mira Trail",
            "email": f"mira-{uuid4().hex[:8]}@ganek-ci.dev",
            "cv_object_key": ticket["object_key"],
            "cv_filename": "cv.pdf",
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _login_and_id(client: AsyncClient, creds: dict[str, str]) -> str:
    assert (await client.post("/api/v1/auth/login", json=creds)).status_code == 200
    items = (await client.get("/api/v1/applications")).json()["items"]
    assert len(items) == 1
    return str(items[0]["id"])


async def _timeline(client: AsyncClient, application_id: str) -> list[dict[str, object]]:
    resp = await client.get(f"/api/v1/applications/{application_id}/timeline")
    assert resp.status_code == 200, resp.text
    rows: list[dict[str, object]] = resp.json()
    stamps = [row["at"] for row in rows]
    assert stamps == sorted(stamps, reverse=True), "newest first"
    return rows


def _kinds(rows: list[dict[str, object]]) -> list[str]:
    return [str(row["kind"]) for row in rows]


async def _finish_quiz(client: AsyncClient, token: str) -> None:
    while True:
        body = (await client.post(f"/api/v1/public/quiz/{token}/next")).json()
        if body["done"]:
            break
        question = body["question"]
        await client.post(
            f"/api/v1/public/quiz/{token}/answer",
            json={"question_id": question["id"], "answer_key": question["options"][0]["key"]},
        )


@pytest.mark.usefixtures("migrated_db", "bucket", "multi_mode")
async def test_applied_and_stage_change_name_the_actor(client: AsyncClient) -> None:
    creds, base = await _company(client, quiz=False)
    await _apply(client, base)
    application_id = await _login_and_id(client, creds)

    rows = await _timeline(client, application_id)
    assert _kinds(rows)[-1] == "applied"  # the oldest row, always there
    assert "application.received" not in _kinds(rows)  # the column carries it

    resp = await client.patch(
        f"/api/v1/applications/{application_id}/stage", json={"stage": "screening"}
    )
    assert resp.status_code == 200, resp.text
    rows = await _timeline(client, application_id)
    move = rows[0]
    assert move["kind"] == "stage.changed"
    assert move["payload"] == {"from": "new", "to": "screening"}
    assert move["actor_email"] == creds["email"]
    assert move["actor_label"]  # display_label fallback, never empty


@pytest.mark.usefixtures("migrated_db", "seeded_bank", "bucket", "multi_mode")
async def test_quiz_invited_started_completed_from_the_attempt(client: AsyncClient) -> None:
    creds, base = await _company(client, quiz=True)
    applied = await _apply(client, base)
    token = applied["quiz_token"]
    assert token is not None

    # one question served = started
    assert (await client.post(f"/api/v1/public/quiz/{token}/next")).status_code == 200
    application_id = await _login_and_id(client, creds)
    kinds = _kinds(await _timeline(client, application_id))
    assert kinds.index("quiz.started") < kinds.index("quiz.invited") < kinds.index("applied")
    assert "quiz.completed" not in kinds

    await client.post("/api/v1/auth/logout")
    await _finish_quiz(client, token)
    assert (await client.post("/api/v1/auth/login", json=creds)).status_code == 200
    rows = await _timeline(client, application_id)
    completed = next(row for row in rows if row["kind"] == "quiz.completed")
    assert isinstance(completed["payload"]["score"], float)  # type: ignore[index]
    assert "quiz.finished" not in _kinds(rows)  # the activity twin is skipped


@pytest.mark.usefixtures("migrated_db", "seeded_bank", "bucket", "multi_mode")
async def test_pending_link_past_its_window_reads_as_expired(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    creds, base = await _company(client, quiz=True)
    await _apply(client, base)
    application_id = await _login_and_id(client, creds)
    assert "quiz.expired" not in _kinds(await _timeline(client, application_id))

    expired_at = datetime.now(UTC) - timedelta(hours=2)
    await db_session.execute(
        update(QuizAttempt)
        .where(QuizAttempt.application_id == UUID(application_id))
        .values(expires_at=expired_at)
    )
    await db_session.commit()
    rows = await _timeline(client, application_id)
    expired = next(row for row in rows if row["kind"] == "quiz.expired")
    assert datetime.fromisoformat(str(expired["at"])) == expired_at


@pytest.mark.usefixtures("migrated_db", "seeded_bank", "bucket", "multi_mode")
async def test_emails_come_from_the_outbox_with_their_state(client: AsyncClient) -> None:
    creds, base = await _company(client, quiz=True)
    await _apply(client, base)
    application_id = await _login_and_id(client, creds)
    assert (await client.post(f"/api/v1/applications/{application_id}/remind")).status_code == 200

    rows = await _timeline(client, application_id)
    emails = [row for row in rows if row["kind"] == "email"]
    templates = [row["payload"]["template"] for row in emails]  # type: ignore[index]
    assert templates[0] == "quiz_reminder"  # newest first
    assert "quiz_invite" in templates  # a quiz job sends the invite as its confirmation
    for row in emails:
        payload = row["payload"]
        assert isinstance(payload, dict)
        assert payload["status"] in {"queued", "sent", "failed", "suppressed"}
        assert set(payload) == {"template", "status", "attempts", "last_error", "subject", "text"}
    # the eager test path renders at delivery, so the text is on the row (PR 4)
    reminder = emails[0]["payload"]
    assert isinstance(reminder, dict)
    assert str(reminder["subject"]).startswith("Your assessment link expires")
    # the candidate's signed link is masked: members read the mail, never
    # hold the capability (same rule as the preview)
    link = re.search(r"Take it now: (\S+)", str(reminder["text"]))
    assert link is not None and link.group(1).endswith("/quiz/personal-link"), reminder["text"]


@pytest.mark.usefixtures("migrated_db", "seeded_bank", "bucket", "multi_mode")
async def test_emails_endpoint_returns_the_rendered_fields(client: AsyncClient) -> None:
    creds, base = await _company(client, quiz=True)
    await _apply(client, base)
    application_id = await _login_and_id(client, creds)
    assert (await client.post(f"/api/v1/applications/{application_id}/remind")).status_code == 200

    resp = await client.get(f"/api/v1/applications/{application_id}/emails")
    assert resp.status_code == 200, resp.text
    rows = resp.json()
    reminder = next(row for row in rows if row["kind"] == "quiz_reminder")
    assert set(reminder) == {
        "id",
        "kind",
        "status",
        "attempts",
        "last_error",
        "created_at",
        "sent_at",
        "subject",
        "text",
    }
    assert reminder["subject"].startswith("Your assessment link expires")
    link = re.search(r"Take it now: (\S+)", reminder["text"])
    assert link is not None and link.group(1).endswith("/quiz/personal-link"), reminder["text"]


@pytest.mark.usefixtures("migrated_db", "bucket", "multi_mode")
async def test_note_added_names_the_author(client: AsyncClient) -> None:
    creds, base = await _company(client, quiz=False)
    await _apply(client, base)
    application_id = await _login_and_id(client, creds)
    resp = await client.post(
        f"/api/v1/applications/{application_id}/notes", json={"body": "Strong portfolio."}
    )
    assert resp.status_code == 201, resp.text

    rows = await _timeline(client, application_id)
    assert rows[0]["kind"] == "note.added"
    assert rows[0]["actor_email"] == creds["email"]
    assert "Strong portfolio" not in str(rows[0]["payload"])  # bodies stay in the notes card


@pytest.mark.usefixtures("migrated_db", "bucket", "multi_mode")
async def test_candidate_withdrawal_is_a_stage_change_without_actor(client: AsyncClient) -> None:
    creds, base = await _company(client, quiz=False)
    applied = await _apply(client, base)
    resp = await client.post(f"/api/v1/public/applications/{applied['status_token']}/withdraw")
    assert resp.status_code == 200, resp.text
    # a repeat click changes nothing and records nothing
    assert (
        await client.post(f"/api/v1/public/applications/{applied['status_token']}/withdraw")
    ).status_code == 200

    application_id = await _login_and_id(client, creds)
    rows = await _timeline(client, application_id)
    moves = [row for row in rows if row["kind"] == "stage.changed"]
    assert len(moves) == 1
    # the candidate's withdrawal records the withdrew reason (PR 2)
    assert moves[0]["payload"] == {"from": "new", "to": "withdrawn", "reason": "withdrew"}
    assert moves[0]["actor_email"] is None and moves[0]["actor_label"] is None


@pytest.mark.usefixtures("migrated_db", "seeded_bank", "bucket", "multi_mode")
async def test_reissue_shows_one_invite_and_one_reissue(client: AsyncClient) -> None:
    creds, base = await _company(client, quiz=True)
    await _apply(client, base)
    application_id = await _login_and_id(client, creds)
    resp = await client.post(f"/api/v1/applications/{application_id}/quiz/reissue")
    assert resp.status_code == 200, resp.text

    kinds = _kinds(await _timeline(client, application_id))
    assert kinds.count("quiz.invited") == 1
    assert kinds.count("quiz.reissued") == 1
    assert "quiz.expired" not in kinds  # the superseded attempt is history, not an expiry


@pytest.mark.usefixtures("migrated_db", "bucket", "multi_mode")
async def test_timeline_is_tenant_scoped(client: AsyncClient) -> None:
    creds, base = await _company(client, quiz=False)
    await _apply(client, base)
    application_id = await _login_and_id(client, creds)
    assert (await client.get(f"/api/v1/applications/{application_id}/timeline")).status_code == 200
    await client.post("/api/v1/auth/logout")

    other_creds, _ = await _company(client, quiz=False)
    assert (await client.post("/api/v1/auth/login", json=other_creds)).status_code == 200
    assert (await client.get(f"/api/v1/applications/{application_id}/timeline")).status_code == 404
