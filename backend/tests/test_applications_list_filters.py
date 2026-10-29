"""Applicant list filters and sort (board card "Applicant list: search, sort,
job column, filters and bulk actions"): search by name or email, score
threshold, quiz state, source, integrity flag, date window, sort keys, the
stage counts and the sources facet, all through GET /applications."""

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models import Application, QuizAttempt
from tests.db import database_reachable, s3_reachable
from tests.helpers import upload_pdf

pytestmark = pytest.mark.skipif(
    not (database_reachable() and s3_reachable()),
    reason="database and object storage required (start postgres+minio or use CI)",
)

PDF_BYTES = b"%PDF-1.4 list filters"

FLAG = {
    "code": "tab_hidden",
    "summary": "left the tab 2x",
    "detail": "The quiz tab was hidden twice.",
    "question_ids": [],
}


@pytest.fixture
def multi_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "mode", "multi")


async def _apply(
    client: AsyncClient,
    base: str,
    *,
    name: str,
    email: str,
    source: str | None,
) -> dict[str, str | None]:
    ticket = (await client.post(f"{base}/apply/upload-url")).json()
    assert (await upload_pdf(ticket, PDF_BYTES)).is_success
    payload: dict[str, object] = {
        "name": name,
        "email": email,
        "cv_object_key": ticket["object_key"],
        "cv_filename": "cv.pdf",
    }
    if source is not None:
        payload["source"] = source
    resp = await client.post(f"{base}/apply", json=payload)
    assert resp.status_code == 201, resp.text
    return resp.json()


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


async def _pipeline(client: AsyncClient, db: AsyncSession) -> dict[str, str]:
    """Two jobs, five applicants, logged in as the admin at the end.

    Returns email by nickname. Shape:
    - erika: Backend (quiz), linkedin, completed, score 90, one flag
    - ben:   Backend (quiz), direct, completed, score 30
    - cara:  Backend (quiz), no source, pending (link still valid)
    - dan:   Backend (quiz), github, pending but the link expired
    - eve:   SRE (no quiz), no source, applied 40 days ago
    """
    creds = {
        "email": f"admin-{uuid4().hex[:8]}@ganek-ci.dev",
        "password": "a-long-secure-password",
    }
    name = f"Filter Co {uuid4().hex[:6]}"
    resp = await client.post("/api/v1/auth/register", json={"company_name": name, **creds})
    assert resp.status_code == 201, resp.text
    slug = name.lower().replace(" ", "-")

    backend = (
        await client.post(
            "/api/v1/jobs",
            json={
                "title": "Backend Engineer",
                "tags": ["python"],
                "quiz_config": {"enabled": True, "question_count": 2},
            },
        )
    ).json()
    sre = (await client.post("/api/v1/jobs", json={"title": "SRE"})).json()
    for job in (backend, sre):
        assert (await client.post(f"/api/v1/jobs/{job['id']}/publish")).status_code == 200
    await client.post("/api/v1/auth/logout")

    backend_base = f"/api/v1/public/companies/{slug}/jobs/{backend['slug']}"
    sre_base = f"/api/v1/public/companies/{slug}/jobs/{sre['slug']}"
    tag = uuid4().hex[:8]
    emails = {
        "erika": f"erika-{tag}@ganek-ci.dev",
        "ben": f"ben-{tag}@ganek-ci.dev",
        "cara": f"cara-{tag}@ganek-ci.dev",
        "dan": f"dan-{tag}@ganek-ci.dev",
        "eve": f"eve-{tag}@sre-ops.dev",
    }
    erika = await _apply(
        client, backend_base, name="Erika Muster", email=emails["erika"], source="linkedin"
    )
    ben = await _apply(client, backend_base, name="Ben Low", email=emails["ben"], source="direct")
    await _apply(client, backend_base, name="Cara Pending", email=emails["cara"], source=None)
    await _apply(client, backend_base, name="Dan Late", email=emails["dan"], source="github")
    await _apply(client, sre_base, name="Eve Ops", email=emails["eve"], source=None)
    for applied in (erika, ben):
        token = applied["quiz_token"]
        assert token is not None
        await _finish_quiz(client, token)

    assert (await client.post("/api/v1/auth/login", json=creds)).status_code == 200
    listed = (await client.get("/api/v1/applications")).json()["items"]
    ids = {row["candidate"]["email"]: UUID(row["id"]) for row in listed}
    assert len(ids) == 5

    # pin the shape the filters are tested against: scores, a flag, an
    # expired link and an old application
    await db.execute(
        update(QuizAttempt)
        .where(QuizAttempt.application_id == ids[emails["erika"]])
        .values(score=0.9, integrity={"flags": [FLAG]})
    )
    await db.execute(
        update(QuizAttempt)
        .where(QuizAttempt.application_id == ids[emails["ben"]])
        .values(score=0.3, integrity={})  # a real run may flag fast answers
    )
    await db.execute(
        update(QuizAttempt)
        .where(QuizAttempt.application_id == ids[emails["dan"]])
        .values(expires_at=datetime.now(UTC) - timedelta(hours=1))
    )
    await db.execute(
        update(Application)
        .where(Application.id == ids[emails["eve"]])
        .values(created_at=datetime.now(UTC) - timedelta(days=40))
    )
    await db.commit()
    return emails


async def _emails(client: AsyncClient, **params: object) -> list[str]:
    resp = await client.get("/api/v1/applications", params=params)
    assert resp.status_code == 200, resp.text
    return [row["candidate"]["email"] for row in resp.json()["items"]]


@pytest.mark.usefixtures("migrated_db", "seeded_bank", "bucket", "multi_mode")
async def test_search_matches_name_or_email_case_insensitively(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    emails = await _pipeline(client, db_session)
    assert await _emails(client, q="ERIKA") == [emails["erika"]]
    assert await _emails(client, q="@sre-ops") == [emails["eve"]]
    assert await _emails(client, q="  low ") == [emails["ben"]]  # trimmed, partial
    assert await _emails(client, q="nobody-here") == []


@pytest.mark.usefixtures("migrated_db", "seeded_bank", "bucket", "multi_mode")
async def test_search_escapes_like_wildcards(client: AsyncClient, db_session: AsyncSession) -> None:
    await _pipeline(client, db_session)
    assert await _emails(client, q="%") == []
    assert await _emails(client, q="_") == []
    assert await _emails(client, q="e_i") == []  # would match "erika" as a LIKE pattern


@pytest.mark.usefixtures("migrated_db", "seeded_bank", "bucket", "multi_mode")
async def test_score_min_keeps_completed_at_or_above(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    emails = await _pipeline(client, db_session)
    assert await _emails(client, score_min=60) == [emails["erika"]]
    assert set(await _emails(client, score_min=30)) == {emails["erika"], emails["ben"]}
    assert set(await _emails(client, score_min=0)) == {emails["erika"], emails["ben"]}
    assert await _emails(client, score_min=91) == []


@pytest.mark.usefixtures("migrated_db", "seeded_bank", "bucket", "multi_mode")
async def test_quiz_state_filter(client: AsyncClient, db_session: AsyncSession) -> None:
    emails = await _pipeline(client, db_session)
    assert set(await _emails(client, quiz="completed")) == {emails["erika"], emails["ben"]}
    # a link past its expiry is "expired" even before the candidate clicks
    # it (the column flips lazily on the next visit)
    assert await _emails(client, quiz="pending") == [emails["cara"]]
    assert await _emails(client, quiz="expired") == [emails["dan"]]
    assert await _emails(client, quiz="in_progress") == []
    assert await _emails(client, quiz="none") == [emails["eve"]]


@pytest.mark.usefixtures("migrated_db", "seeded_bank", "bucket", "multi_mode")
async def test_quiz_filters_use_the_latest_attempt(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    emails = await _pipeline(client, db_session)
    listed = (await client.get("/api/v1/applications", params={"q": "ben"})).json()["items"]
    ben_id = listed[0]["id"]
    resp = await client.post(f"/api/v1/applications/{ben_id}/quiz/reissue")
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "pending"

    assert await _emails(client, quiz="completed") == [emails["erika"]]
    assert set(await _emails(client, quiz="pending")) == {emails["cara"], emails["ben"]}
    assert await _emails(client, score_min=0) == [emails["erika"]]


@pytest.mark.usefixtures("migrated_db", "seeded_bank", "bucket", "multi_mode")
async def test_source_filter_direct_includes_null(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    emails = await _pipeline(client, db_session)
    assert set(await _emails(client, source="direct")) == {
        emails["ben"],
        emails["cara"],
        emails["eve"],
    }
    assert await _emails(client, source="linkedin") == [emails["erika"]]
    assert await _emails(client, source="github") == [emails["dan"]]
    assert await _emails(client, source="indeed") == []


@pytest.mark.usefixtures("migrated_db", "seeded_bank", "bucket", "multi_mode")
async def test_flagged_filter(client: AsyncClient, db_session: AsyncSession) -> None:
    emails = await _pipeline(client, db_session)
    assert await _emails(client, flagged="true") == [emails["erika"]]
    clean = set(await _emails(client, flagged="false"))
    assert clean == {emails["ben"], emails["cara"], emails["dan"], emails["eve"]}


@pytest.mark.usefixtures("migrated_db", "seeded_bank", "bucket", "multi_mode")
async def test_since_days_filter(client: AsyncClient, db_session: AsyncSession) -> None:
    emails = await _pipeline(client, db_session)
    recent = await _emails(client, since_days=30)
    assert emails["eve"] not in recent
    assert len(recent) == 4
    assert emails["eve"] in await _emails(client, since_days=90)


@pytest.mark.usefixtures("migrated_db", "seeded_bank", "bucket", "multi_mode")
async def test_sort_keys(client: AsyncClient, db_session: AsyncSession) -> None:
    emails = await _pipeline(client, db_session)
    newest = await _emails(client)
    assert newest[0] == emails["dan"]  # eve applied last but is backdated 40 days
    assert newest[-1] == emails["eve"]
    assert await _emails(client, sort="applied_asc") == list(reversed(newest))

    by_score = await _emails(client, sort="score_desc")
    assert by_score[:2] == [emails["erika"], emails["ben"]]
    assert set(by_score[2:]) == {emails["cara"], emails["dan"], emails["eve"]}  # nulls last
    low_first = await _emails(client, sort="score_asc")
    assert low_first[:2] == [emails["ben"], emails["erika"]]

    assert await _emails(client, sort="name_asc") == [
        emails["ben"],
        emails["cara"],
        emails["dan"],
        emails["erika"],
        emails["eve"],
    ]


@pytest.mark.usefixtures("migrated_db", "seeded_bank", "bucket", "multi_mode")
async def test_stage_counts_follow_the_other_filters_but_not_the_stage(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    emails = await _pipeline(client, db_session)
    listed = (await client.get("/api/v1/applications", params={"q": "erika"})).json()["items"]
    erika_id = listed[0]["id"]
    assert (
        await client.patch(f"/api/v1/applications/{erika_id}/stage", json={"stage": "screening"})
    ).status_code == 200

    page = (
        await client.get("/api/v1/applications", params={"quiz": "completed", "stage": "new"})
    ).json()
    assert [row["candidate"]["email"] for row in page["items"]] == [emails["ben"]]
    assert page["total"] == 1
    # the pill counts cover every completed quiz, whatever pill is active
    assert page["stage_counts"] == {"new": 1, "screening": 1}


@pytest.mark.usefixtures("migrated_db", "seeded_bank", "bucket", "multi_mode")
async def test_sources_facet_lists_distinct_values(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _pipeline(client, db_session)
    page = (await client.get("/api/v1/applications", params={"q": "nobody"})).json()
    # the facet is company-wide so an empty result still offers the options
    assert page["sources"] == ["direct", "github", "linkedin"]


@pytest.mark.usefixtures("migrated_db", "bucket", "multi_mode")
async def test_filter_validation(client: AsyncClient) -> None:
    creds = {
        "email": f"admin-{uuid4().hex[:8]}@ganek-ci.dev",
        "password": "a-long-secure-password",
    }
    resp = await client.post(
        "/api/v1/auth/register", json={"company_name": f"Valid Co {uuid4().hex[:6]}", **creds}
    )
    assert resp.status_code == 201
    for params in (
        {"score_min": 101},
        {"score_min": -1},
        {"since_days": 0},
        {"since_days": 366},
        {"sort": "bogus"},
        {"quiz": "bogus"},
        {"q": "x" * 201},
    ):
        resp = await client.get("/api/v1/applications", params=params)
        assert resp.status_code == 422, (params, resp.text)
    assert (await client.get("/api/v1/applications", params={"q": ""})).status_code == 200
