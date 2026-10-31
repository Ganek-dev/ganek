"""Screening answers through the public apply route (board card "Per-job
screening questions"): validation against the job's list, the write-once
snapshot the recruiter sees, the candidate-facing shapes that never carry
``preferred`` or ``match``, and the anti-goal: an answer never changes the
stage, never queues a mail, never touches the quiz."""

import csv
import io
import json
from typing import Any
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models import EmailOutbox
from tests.db import database_reachable, s3_reachable
from tests.helpers import upload_pdf

pytestmark = pytest.mark.skipif(
    not (database_reachable() and s3_reachable()),
    reason="database and object storage required (start postgres+minio or use CI)",
)

PDF_BYTES = b"%PDF-1.4 screening apply"
QUESTIONS: list[dict[str, Any]] = [
    {
        "id": "sq_0000aa01",
        "type": "yes_no",
        "prompt": "Can you work in Germany?",
        "preferred": "yes",
        "required": True,
    },
    {
        "id": "sq_0000aa02",
        "type": "single_choice",
        "prompt": "Days on site?",
        "options": ["0", "1-2", "3+"],
        "preferred": "1-2",
    },
    {"id": "sq_0000aa03", "type": "short_text", "prompt": "Notice period?"},
    {
        "id": "sq_0000aa04",
        "type": "acknowledgment",
        "prompt": "I confirm the information is accurate",
    },
]
GOOD_ANSWERS = [
    {"question_id": "sq_0000aa01", "answer": "no"},
    {"question_id": "sq_0000aa02", "answer": "1-2"},
    {"question_id": "sq_0000aa03", "answer": "4 weeks"},
    {"question_id": "sq_0000aa04", "answer": True},
]


@pytest.fixture
def multi_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "mode", "multi")


async def _publish(
    client: AsyncClient, questions: list[dict[str, Any]] | None
) -> tuple[str, dict[str, str]]:
    """Register + publish a job (optionally with questions); logged out at
    the end; returns (public base path, admin creds)."""
    creds = {"email": f"admin-{uuid4().hex[:8]}@ganek-ci.dev", "password": "a-long-secure-password"}
    name = f"Screen Co {uuid4().hex[:6]}"
    resp = await client.post("/api/v1/auth/register", json={"company_name": name, **creds})
    assert resp.status_code == 201, resp.text
    payload: dict[str, Any] = {"title": "Backend Engineer"}
    if questions is not None:
        payload["screening_questions"] = questions
    job = (await client.post("/api/v1/jobs", json=payload)).json()
    assert (await client.post(f"/api/v1/jobs/{job['id']}/publish")).status_code == 200
    await client.post("/api/v1/auth/logout")
    slug = name.lower().replace(" ", "-")
    return f"/api/v1/public/companies/{slug}/jobs/{job['slug']}", creds


async def _apply(client: AsyncClient, base: str, **extra: Any) -> Any:
    ticket = (await client.post(f"{base}/apply/upload-url")).json()
    assert (await upload_pdf(ticket, PDF_BYTES)).is_success
    return await client.post(
        f"{base}/apply",
        json={
            "name": "Marta Vidal",
            "email": f"marta-{uuid4().hex[:8]}@ganek-ci.dev",
            "cv_object_key": ticket["object_key"],
            "cv_filename": "marta.pdf",
            **extra,
        },
    )


async def _admin_application(client: AsyncClient, creds: dict[str, str]) -> dict[str, Any]:
    assert (await client.post("/api/v1/auth/login", json=creds)).status_code == 200
    items = (await client.get("/api/v1/applications")).json()["items"]
    assert len(items) == 1
    return (await client.get(f"/api/v1/applications/{items[0]['id']}")).json()


@pytest.mark.usefixtures("migrated_db", "bucket", "multi_mode")
async def test_apply_stores_snapshots_with_match_and_admin_sees_them(client: AsyncClient) -> None:
    base, creds = await _publish(client, QUESTIONS)
    resp = await _apply(client, base, screening_answers=GOOD_ANSWERS)
    assert resp.status_code == 201, resp.text
    app = await _admin_application(client, creds)
    answers = app["screening_answers"]
    assert [a["question_id"] for a in answers] == [q["id"] for q in QUESTIONS]
    assert [a["match"] for a in answers] == [False, True, None, None]
    assert answers[0]["preferred"] == "yes"
    assert answers[0]["answer"] == "no"
    assert answers[0]["prompt"] == "Can you work in Germany?"
    assert answers[3]["answer"] is True


@pytest.mark.usefixtures("migrated_db", "bucket", "multi_mode")
async def test_apply_refuses_bad_answers_with_the_question_id(client: AsyncClient) -> None:
    base, _ = await _publish(client, QUESTIONS)
    missing_required = [a for a in GOOD_ANSWERS if a["question_id"] != "sq_0000aa01"]
    resp = await _apply(client, base, screening_answers=missing_required)
    assert resp.status_code == 422, resp.text
    assert resp.json()["detail"][0]["question_id"] == "sq_0000aa01"
    bad_option = [
        {**a, "answer": "7"} if a["question_id"] == "sq_0000aa02" else a for a in GOOD_ANSWERS
    ]
    assert (await _apply(client, base, screening_answers=bad_option)).status_code == 422
    unknown = [*GOOD_ANSWERS, {"question_id": "sq_0000ffff", "answer": "x"}]
    assert (await _apply(client, base, screening_answers=unknown)).status_code == 422


@pytest.mark.usefixtures("migrated_db", "bucket", "multi_mode")
async def test_answers_never_change_stage_mail_or_quiz(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """Hard rule 5: a mismatch on every preferred answer is still a plain
    new application with the same one confirmation mail as any other."""
    base, creds = await _publish(client, QUESTIONS)
    mismatching = [
        {"question_id": "sq_0000aa01", "answer": "no"},
        {"question_id": "sq_0000aa02", "answer": "3+"},
        {"question_id": "sq_0000aa04", "answer": True},
    ]
    assert (await _apply(client, base, screening_answers=mismatching)).status_code == 201
    app = await _admin_application(client, creds)
    assert app["stage"] == "new"
    assert app["quiz_attempt"] is None  # the job has no quiz; answers never create one
    assert [a["match"] for a in app["screening_answers"]] == [False, False, None, None]
    mails = (
        await db_session.execute(
            select(func.count())
            .select_from(EmailOutbox)
            .where(EmailOutbox.application_id == UUID(app["id"]))
        )
    ).scalar_one()
    assert mails == 1  # application_received, exactly as without answers
    kinds = (
        (
            await db_session.execute(
                select(EmailOutbox.kind).where(EmailOutbox.application_id == UUID(app["id"]))
            )
        )
        .scalars()
        .all()
    )
    assert list(kinds) == ["application_received"]


@pytest.mark.usefixtures("migrated_db", "bucket", "multi_mode")
async def test_status_page_and_dsar_show_answers_without_preferred_or_match(
    client: AsyncClient,
) -> None:
    base, creds = await _publish(client, QUESTIONS)
    received = (await _apply(client, base, screening_answers=GOOD_ANSWERS)).json()
    status_body = (
        await client.get(f"/api/v1/public/applications/{received['status_token']}")
    ).json()
    assert status_body["screening_answers"] == [
        {"prompt": "Can you work in Germany?", "answer": "no"},
        {"prompt": "Days on site?", "answer": "1-2"},
        {"prompt": "Notice period?", "answer": "4 weeks"},
        {"prompt": "I confirm the information is accurate", "answer": True},
    ]
    dumped = json.dumps(status_body)
    assert "preferred" not in dumped and '"match"' not in dumped

    app = await _admin_application(client, creds)
    bundle = (await client.get(f"/api/v1/applications/{app['id']}/dsar-export")).json()
    assert bundle["applications"][0]["screening_answers"][0] == {
        "prompt": "Can you work in Germany?",
        "answer": "no",
    }
    dumped = json.dumps(bundle)
    assert "preferred" not in dumped and '"match"' not in dumped


@pytest.mark.usefixtures("migrated_db", "bucket", "multi_mode")
async def test_job_without_questions_keeps_an_empty_list(client: AsyncClient) -> None:
    base, creds = await _publish(client, None)
    assert (await _apply(client, base)).status_code == 201
    app = await _admin_application(client, creds)
    assert app["screening_answers"] == []
    # answers for a job without questions are refused, not silently dropped
    await client.post("/api/v1/auth/logout")
    resp = await _apply(
        client, base, screening_answers=[{"question_id": "sq_0000aa01", "answer": "yes"}]
    )
    assert resp.status_code == 422


async def _email(client: AsyncClient, base: str, answers: list[dict[str, Any]] | None) -> str:
    email = f"cand-{uuid4().hex[:8]}@ganek-ci.dev"
    ticket = (await client.post(f"{base}/apply/upload-url")).json()
    assert (await upload_pdf(ticket, PDF_BYTES)).is_success
    payload: dict[str, Any] = {
        "name": "Cand Idate",
        "email": email,
        "cv_object_key": ticket["object_key"],
        "cv_filename": "cv.pdf",
    }
    if answers is not None:
        payload["screening_answers"] = answers
    resp = await client.post(f"{base}/apply", json=payload)
    assert resp.status_code == 201, resp.text
    return email


@pytest.mark.usefixtures("migrated_db", "bucket", "multi_mode")
async def test_screening_filter_and_export_column(client: AsyncClient) -> None:
    """Four applicants: all preferred matched, one mismatch, one skipped
    optional, and one on a job without questions (legacy shape)."""
    creds = {"email": f"admin-{uuid4().hex[:8]}@ganek-ci.dev", "password": "a-long-secure-password"}
    name = f"Filter Co {uuid4().hex[:6]}"
    resp = await client.post("/api/v1/auth/register", json={"company_name": name, **creds})
    assert resp.status_code == 201, resp.text
    slug = name.lower().replace(" ", "-")
    screened = (
        await client.post(
            "/api/v1/jobs", json={"title": "Screened", "screening_questions": QUESTIONS}
        )
    ).json()
    plain = (await client.post("/api/v1/jobs", json={"title": "Plain"})).json()
    for job in (screened, plain):
        assert (await client.post(f"/api/v1/jobs/{job['id']}/publish")).status_code == 200
    await client.post("/api/v1/auth/logout")
    screened_base = f"/api/v1/public/companies/{slug}/jobs/{screened['slug']}"
    plain_base = f"/api/v1/public/companies/{slug}/jobs/{plain['slug']}"

    ack = {"question_id": "sq_0000aa04", "answer": True}
    matched = await _email(
        client,
        screened_base,
        [
            {"question_id": "sq_0000aa01", "answer": "yes"},
            {"question_id": "sq_0000aa02", "answer": "1-2"},
            {"question_id": "sq_0000aa03", "answer": "now"},
            ack,
        ],
    )
    mismatched = await _email(
        client,
        screened_base,
        [
            {"question_id": "sq_0000aa01", "answer": "no"},
            {"question_id": "sq_0000aa02", "answer": "3+"},
            {"question_id": "sq_0000aa03", "answer": "8 weeks"},
            ack,
        ],
    )
    skipped = await _email(
        client, screened_base, [{"question_id": "sq_0000aa01", "answer": "yes"}, ack]
    )
    legacy = await _email(client, plain_base, None)

    assert (await client.post("/api/v1/auth/login", json=creds)).status_code == 200

    async def emails_for(screening: str | None) -> set[str]:
        params = {"screening": screening} if screening else {}
        page = (await client.get("/api/v1/applications", params=params)).json()
        return {item["candidate"]["email"] for item in page["items"]}

    assert await emails_for(None) == {matched, mismatched, skipped, legacy}
    # skipping a preferred question is not a mismatch, so the applicant who
    # answered one preferred question right and skipped the other is "all
    # preferred" too; they show under Unanswered as well
    assert await emails_for("match") == {matched, skipped}
    assert await emails_for("mismatch") == {mismatched}
    assert await emails_for("unanswered") == {skipped}
    assert (
        await client.get("/api/v1/applications", params={"screening": "nope"})
    ).status_code == 422

    resp = await client.get("/api/v1/applications/export", params={"format": "csv"})
    rows = {row["candidate_email"]: row for row in csv.DictReader(io.StringIO(resp.text))}
    assert rows[matched]["screening_mismatches"] == "0"
    assert rows[mismatched]["screening_mismatches"] == "2"
    assert rows[skipped]["screening_mismatches"] == "0"
    assert rows[legacy]["screening_mismatches"] == ""
    header = resp.text.splitlines()[0].split(",")
    assert header.index("screening_mismatches") == header.index("message") + 1
    for secret in ("preferred", "sq_0000aa01"):
        assert secret not in resp.text  # no question internals in the sheet

    resp = await client.get(
        "/api/v1/applications/export", params={"format": "csv", "screening": "mismatch"}
    )
    assert [row["candidate_email"] for row in csv.DictReader(io.StringIO(resp.text))] == [
        mismatched
    ]
