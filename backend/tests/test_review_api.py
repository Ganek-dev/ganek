"""The reviewer judging view (spec 4.1, 4.5): grants, hidden colleagues, and
what must never reach a reviewer."""

import json
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import event, select
from sqlalchemy.engine import Engine
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.access import can_open_application, granted_application_ids
from app.models import (
    AccessLog,
    Application,
    ApplicationStage,
    AttemptAnswer,
    AttemptStatus,
    Candidate,
    Company,
    Interview,
    InterviewStatus,
    Question,
    QuestionSource,
    QuizAttempt,
    Scorecard,
    User,
)
from app.services import interviews as interviews_service
from tests.db import database_reachable
from tests.test_reviewer_gate import Env, _env, _invite_reviewer, _request_from_admin
from tests.test_scorecards_api import Co, _company, _login

pytestmark = pytest.mark.skipif(
    not database_reachable(), reason="database not reachable (start postgres or use CI)"
)

LIST_URL = "/api/v1/review/applications"
FORBIDDEN_KEYS = {
    "correct_key",
    "options",
    "answer_key",
    "explanation_md",
    "email",
    "candidate_email",
    "notes",
    "note",
    "integrity",
    "integrity_events",
    "per_tag_scores",
    "rejection_reason",
    "rejection_note",
    "preferred",
    "match",
    "message",
    "source",
}


@pytest.fixture(autouse=True)
def multi_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core.config import settings

    monkeypatch.setattr(settings, "mode", "multi")


def _detail(application_id: object) -> str:
    return f"{LIST_URL}/{application_id}"


def _keys(value: Any) -> Iterator[str]:
    if isinstance(value, dict):
        for key, item in value.items():
            yield key
            yield from _keys(item)
    elif isinstance(value, list):
        for item in value:
            yield from _keys(item)


async def _second_application(db: AsyncSession, co: Co, *, name: str = "Second Person") -> str:
    first = await db.get(Application, UUID(co.application_id))
    assert first is not None
    candidate = Candidate(
        company_id=first.company_id, email=f"c-{uuid4().hex[:8]}@x.dev", name=name
    )
    db.add(candidate)
    await db.flush()
    application = Application(
        company_id=first.company_id,
        job_id=first.job_id,
        candidate_id=candidate.id,
        cv_object_key=f"cvs/{uuid4().hex}.pdf",
        cv_filename="cv.pdf",
        cv_size=1,
    )
    db.add(application)
    await db.commit()
    return str(application.id)


async def _request(client: AsyncClient, application_id: str, reviewer_id: str) -> None:
    resp = await client.post(
        f"/api/v1/scorecards/applications/{application_id}",
        json={"reviewer_user_id": reviewer_id},
    )
    assert resp.status_code == 201, resp.text


async def _submit(
    client: AsyncClient, co: Co, *, recommendation: str = "yes", comment: str = "Solid"
) -> None:
    resp = await client.put(
        f"/api/v1/scorecards/applications/{co.application_id}/mine",
        json={
            "ratings": {co.criterion_id: 3},
            "recommendation": recommendation,
            "comment": comment,
        },
    )
    assert resp.status_code == 200, resp.text


async def _booked_interview(db: AsyncSession, env: Env, *, location: str = "Room 4") -> Interview:
    """Through the real service, so the auto-request fires like in production."""
    application = await db.get(Application, UUID(env.co.application_id))
    interviewer = await db.get(User, UUID(env.reviewer_id))
    assert application is not None
    assert interviewer is not None
    company = await db.get(Company, application.company_id)
    assert company is not None
    interview = await interviews_service.create_interview(
        db,
        company,
        application,
        interviewer=interviewer,
        title="Hiring manager interview",
        description="",
        duration_minutes=45,
        timezone="Europe/Berlin",
        location=location,
    )
    await db.commit()
    return interview


async def _book(db: AsyncSession, env: Env, interview: Interview) -> None:
    interviewer = await db.get(User, UUID(env.reviewer_id))
    assert interviewer is not None
    slots = await interviews_service.generate_slots(
        db, interviewer, duration_minutes=45, timezone="Europe/Berlin"
    )
    await interviews_service.book(db, interview, start=slots[0])
    await db.commit()


async def _seed_quiz(
    db: AsyncSession, application_id: str, *, status: AttemptStatus = AttemptStatus.COMPLETED
) -> None:
    """Four questions, one per outcome. Every option text and internal field
    carries a sentinel the response must not echo."""
    application = await db.get(Application, UUID(application_id))
    assert application is not None
    now = datetime.now(UTC)
    questions = [
        Question(
            id=f"rv-{uuid4().hex[:16]}",
            company_id=application.company_id,
            domain="company",
            tags=["TAG-SENTINEL"],
            difficulty=2,
            prompt_md=f"Prompt {kind}?",
            options={"a": f"OPTION-{kind}-A", "b": f"OPTION-{kind}-B"},
            correct_key="a",
            explanation_md="EXPLANATION-SENTINEL",
            source=QuestionSource.COMPANY,
        )
        for kind in ("correct", "wrong", "timeout", "never")
    ]
    db.add_all(questions)
    await db.flush()
    attempt = QuizAttempt(
        company_id=application.company_id,
        application_id=application.id,
        status=status,
        question_ids=[q.id for q in questions],
        expires_at=now + timedelta(days=1),
        score=25.0,
        per_tag_scores={"TAG-SENTINEL": 25},
        integrity={"events": [{"type": "paste", "note": "INTEGRITY-SENTINEL"}], "paste_count": 3},
    )
    db.add(attempt)
    await db.flush()
    served = now - timedelta(minutes=10)
    resolved = [(questions[0], "a", True), (questions[1], "b", False), (questions[2], None, False)]
    for index, (question, key, is_correct) in enumerate(resolved):
        db.add(
            AttemptAnswer(
                attempt_id=attempt.id,
                question_id=question.id,
                option_order=["a", "b"],
                served_at=served + timedelta(minutes=index),
                deadline_at=served + timedelta(minutes=index, seconds=15),
                answered_at=served + timedelta(minutes=index, seconds=10),
                answer_key=key,
                is_correct=is_correct,
            )
        )
    await db.commit()


@pytest.mark.usefixtures("migrated_db")
async def test_reviewer_list_shows_only_granted(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    env = await _env(client, db_session)
    other = await _second_application(db_session, env.co)
    await _request_from_admin(client, env, env.reviewer_id)
    await _login(client, env.reviewer)

    resp = await client.get(LIST_URL)
    assert resp.status_code == 200, resp.text
    (item,) = resp.json()
    assert item["application_id"] == env.co.application_id
    assert item["candidate_name"] == "Marta Vidal"
    assert item["job_title"] == "Backend"
    assert item["stage_label"] == "New"
    assert item["scorecard_state"] == "open"
    assert item["scorecard_due_from"] is not None
    assert item["interview_start"] is None
    assert set(item) == {
        "application_id",
        "candidate_name",
        "job_title",
        "stage_label",
        "scorecard_state",
        "scorecard_due_from",
        "interview_start",
    }

    assert (await client.get(_detail(env.co.application_id))).status_code == 200
    assert (await client.get(_detail(other))).status_code == 404


@pytest.mark.usefixtures("migrated_db")
async def test_interview_grant_and_cancel(client: AsyncClient, db_session: AsyncSession) -> None:
    env = await _env(client, db_session)
    interview = await _booked_interview(db_session, env)
    url = _detail(env.co.application_id)

    # pending: no time yet, no grant
    assert (await client.get(url)).status_code == 404
    assert (await client.get(LIST_URL)).json() == []

    await _book(db_session, env, interview)
    resp = await client.get(url)
    assert resp.status_code == 200, resp.text
    assert resp.json()["interview"]["location"] == "Room 4"
    assert resp.json()["interview"]["duration_minutes"] == 45
    assert resp.json()["interview"]["timezone"] == "Europe/Berlin"
    assert resp.json()["interview"]["scheduled_start"] is not None
    (item,) = (await client.get(LIST_URL)).json()
    assert item["interview_start"] is not None

    interviewer = await db_session.get(User, UUID(env.reviewer_id))
    assert interviewer is not None
    await interviews_service.cancel_interview(db_session, interview, interviewer=interviewer)
    await db_session.commit()

    # the cancel also dismissed the auto-request, so no grant remains
    assert (await client.get(url)).status_code == 404
    assert (await client.get(LIST_URL)).json() == []


@pytest.mark.usefixtures("migrated_db")
async def test_cancelled_interview_with_a_time_grants_nothing(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    env = await _env(client, db_session)
    application = await db_session.get(Application, UUID(env.co.application_id))
    assert application is not None
    db_session.add(
        Interview(
            company_id=application.company_id,
            application_id=application.id,
            interviewer_user_id=UUID(env.reviewer_id),
            duration_minutes=30,
            timezone="UTC",
            status=InterviewStatus.CANCELLED,
            scheduled_start=datetime.now(UTC) + timedelta(days=1),
        )
    )
    await db_session.commit()
    assert (await client.get(_detail(env.co.application_id))).status_code == 404


@pytest.mark.usefixtures("migrated_db")
async def test_detail_hides_others_until_submitted(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    env = await _env(client, db_session)
    await _request_from_admin(client, env, env.reviewer_id)
    await _request_from_admin(client, env, env.co.member_id)
    await _login(client, env.co.member)
    await _submit(client, env.co, recommendation="strong_yes", comment="Colleague comment")

    await _login(client, env.reviewer)
    url = _detail(env.co.application_id)
    body = (await client.get(url)).json()
    assert body["others"] == []
    assert body["hidden_until_submitted"] is True
    assert body["mine"]["state"] == "open"
    assert "Colleague comment" not in json.dumps(body)

    await _submit(client, env.co, comment="My comment")
    body = (await client.get(url)).json()
    assert body["hidden_until_submitted"] is False
    assert body["mine"]["state"] == "submitted"
    assert body["mine"]["can_edit"] is True
    (other,) = body["others"]
    assert other["recommendation"] == "strong_yes"
    assert other["comment"] == "Colleague comment"
    assert other["reviewer_user_id"] == env.co.member_id
    assert other["can_edit"] is False


@pytest.mark.usefixtures("migrated_db")
async def test_open_colleague_row_stays_out_of_others(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    env = await _env(client, db_session)
    await _request_from_admin(client, env, env.reviewer_id)
    await _request_from_admin(client, env, env.co.member_id)
    await _login(client, env.reviewer)
    await _submit(client, env.co)
    body = (await client.get(_detail(env.co.application_id))).json()
    assert body["others"] == []
    assert body["hidden_until_submitted"] is False


@pytest.mark.usefixtures("migrated_db")
async def test_declined_keeps_the_grant_and_stays_hidden(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    env = await _env(client, db_session)
    await _request_from_admin(client, env, env.reviewer_id)
    await _request_from_admin(client, env, env.co.member_id)
    await _login(client, env.co.member)
    await _submit(client, env.co)

    await _login(client, env.reviewer)
    declined = await client.post(
        f"/api/v1/scorecards/applications/{env.co.application_id}/mine/decline"
    )
    assert declined.status_code == 204, declined.text
    resp = await client.get(_detail(env.co.application_id))
    assert resp.status_code == 200, resp.text
    assert resp.json()["mine"]["state"] == "declined"
    assert resp.json()["others"] == []
    assert resp.json()["hidden_until_submitted"] is True


@pytest.mark.usefixtures("migrated_db")
async def test_dismissed_request_removes_the_grant(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    env = await _env(client, db_session)
    row = await _request_from_admin(client, env, env.reviewer_id)
    resp = await client.post(f"/api/v1/scorecards/{row['id']}/dismiss")
    assert resp.status_code == 204, resp.text
    await _login(client, env.reviewer)
    assert (await client.get(_detail(env.co.application_id))).status_code == 404
    assert (await client.get(LIST_URL)).json() == []


@pytest.mark.usefixtures("migrated_db")
async def test_interview_grant_without_a_row_keeps_colleagues_hidden(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """The recruiter dismissed the auto-request but the interview stands: the
    grant holds through the interview and mine is empty, not the dismissed row."""
    env = await _env(client, db_session)
    interview = await _booked_interview(db_session, env)
    await _book(db_session, env, interview)
    await _request_from_admin(client, env, env.co.member_id)
    await _login(client, env.co.member)
    await _submit(client, env.co)

    await _login(client, env.co.admin)
    mine_row = (
        await db_session.execute(
            select(Scorecard).where(Scorecard.reviewer_user_id == UUID(env.reviewer_id))
        )
    ).scalar_one()
    resp = await client.post(f"/api/v1/scorecards/{mine_row.id}/dismiss")
    assert resp.status_code == 204, resp.text

    await _login(client, env.reviewer)
    resp = await client.get(_detail(env.co.application_id))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["mine"] is None
    assert body["others"] == []
    assert body["hidden_until_submitted"] is True
    assert body["interview"] is not None
    (item,) = (await client.get(LIST_URL)).json()
    assert item["scorecard_state"] is None
    assert item["scorecard_due_from"] is None


@pytest.mark.usefixtures("migrated_db")
async def test_another_teammates_interview_is_not_shown(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    env = await _env(client, db_session)
    await _request_from_admin(client, env, env.reviewer_id)
    application = await db_session.get(Application, UUID(env.co.application_id))
    assert application is not None
    db_session.add(
        Interview(
            company_id=application.company_id,
            application_id=application.id,
            interviewer_user_id=UUID(env.co.member_id),
            duration_minutes=30,
            timezone="UTC",
            status=InterviewStatus.BOOKED,
            scheduled_start=datetime.now(UTC) + timedelta(days=1),
            location="Secret room",
        )
    )
    await db_session.commit()
    await _login(client, env.reviewer)
    resp = await client.get(_detail(env.co.application_id))
    assert resp.status_code == 200, resp.text
    assert resp.json()["interview"] is None
    assert "Secret room" not in resp.text
    assert (await client.get(LIST_URL)).json()[0]["interview_start"] is None


@pytest.mark.usefixtures("migrated_db")
async def test_crafted_rows_in_another_company_never_grant(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """Rows are hand-written past the services: each one names the reviewer on
    an application of a different company."""
    foreign = await _company(client, db_session)
    env = await _env(client, db_session)
    reviewer = await db_session.get(User, UUID(env.reviewer_id))
    assert reviewer is not None
    apps = [foreign.application_id]
    for _ in range(3):
        apps.append(await _second_application(db_session, foreign))
    own_apps = [await _second_application(db_session, env.co) for _ in range(2)]
    foreign_app = await db_session.get(Application, UUID(apps[0]))
    assert foreign_app is not None
    foreign_company = foreign_app.company_id
    start = datetime.now(UTC) + timedelta(days=1)

    def scorecard(application_id: str, company_id: UUID) -> Scorecard:
        return Scorecard(
            company_id=company_id,
            application_id=UUID(application_id),
            job_id=foreign_app.job_id,
            reviewer_user_id=reviewer.id,
            due_from=start,
        )

    def interview(application_id: str, company_id: UUID) -> Interview:
        return Interview(
            company_id=company_id,
            application_id=UUID(application_id),
            interviewer_user_id=reviewer.id,
            duration_minutes=30,
            timezone="UTC",
            status=InterviewStatus.BOOKED,
            scheduled_start=start,
        )

    db_session.add_all(
        [
            # the row claims the foreign company
            scorecard(apps[0], foreign_company),
            interview(apps[1], foreign_company),
            # the row claims the reviewer's company, the application disagrees
            scorecard(apps[2], reviewer.company_id),
            interview(apps[3], reviewer.company_id),
            # the application is the reviewer's, the row claims the foreign company
            scorecard(own_apps[0], foreign_company),
            interview(own_apps[1], foreign_company),
        ]
    )
    await db_session.commit()

    assert await granted_application_ids(db_session, reviewer) == set()
    for application_id in apps + own_apps:
        assert not await can_open_application(db_session, reviewer, UUID(application_id))
    await _login(client, env.reviewer)
    assert (await client.get(LIST_URL)).json() == []
    for application_id in apps + own_apps:
        assert (await client.get(_detail(application_id))).status_code == 404


@pytest.mark.usefixtures("migrated_db")
async def test_grants_are_per_reviewer(client: AsyncClient, db_session: AsyncSession) -> None:
    env = await _env(client, db_session)
    await _login(client, env.co.admin)
    _, second_id = await _invite_reviewer(client)
    await _request_from_admin(client, env, second_id)
    await _login(client, env.reviewer)
    assert (await client.get(_detail(env.co.application_id))).status_code == 404


@pytest.mark.usefixtures("migrated_db")
async def test_detail_never_leaks_keys(client: AsyncClient, db_session: AsyncSession) -> None:
    env = await _env(client, db_session)
    await _seed_quiz(db_session, env.co.application_id)
    application = await db_session.get(Application, UUID(env.co.application_id))
    assert application is not None
    candidate = await db_session.get(Candidate, application.candidate_id)
    assert candidate is not None
    application.stage = ApplicationStage.REJECTED
    application.rejection_reason = "REASON-SENTINEL"
    application.rejection_note = "REJECTION-NOTE-SENTINEL"
    application.message = "MESSAGE-SENTINEL"
    application.source = "SOURCE-SENTINEL"
    application.screening_answers = [
        {
            "id": "q1",
            "prompt": "Work permit?",
            "type": "yes_no",
            "preferred": "PREFERRED-SENTINEL",
            "answer": "yes",
            "match": False,
        }
    ]
    await db_session.commit()
    await _request_from_admin(client, env, env.reviewer_id)
    note = await client.post(
        f"/api/v1/applications/{env.co.application_id}/notes", json={"body": "NOTE-SENTINEL"}
    )
    assert note.status_code == 201, note.text

    await _login(client, env.reviewer)
    resp = await client.get(_detail(env.co.application_id))
    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert body["candidate_name"] == "Marta Vidal"
    assert body["screening_answers"] == [{"prompt": "Work permit?", "answer": "yes"}]
    quiz = body["quiz"]
    assert quiz["score"] == 25.0
    assert (quiz["correct"], quiz["total"], quiz["timed_out"]) == (1, 4, 1)
    assert quiz["questions"] == [
        {"prompt": "Prompt correct?", "outcome": "correct"},
        {"prompt": "Prompt wrong?", "outcome": "wrong"},
        {"prompt": "Prompt timeout?", "outcome": "timed_out"},
        {"prompt": "Prompt never?", "outcome": "unanswered"},
    ]

    for text in (resp.text, (await client.get(LIST_URL)).text):
        assert candidate.email not in text
        for needle in (
            "correct_key",
            "OPTION-",
            "EXPLANATION-SENTINEL",
            "TAG-SENTINEL",
            "INTEGRITY-SENTINEL",
            "paste_count",
            "NOTE-SENTINEL",
            "REASON-SENTINEL",
            "REJECTION-NOTE-SENTINEL",
            "MESSAGE-SENTINEL",
            "SOURCE-SENTINEL",
            "PREFERRED-SENTINEL",
        ):
            assert needle not in text, needle
    assert not FORBIDDEN_KEYS & set(_keys(body))
    assert not FORBIDDEN_KEYS & set(_keys((await client.get(LIST_URL)).json()))


@pytest.mark.usefixtures("migrated_db")
@pytest.mark.parametrize("status", [AttemptStatus.PENDING, AttemptStatus.IN_PROGRESS])
async def test_unfinished_quiz_has_no_summary(
    client: AsyncClient, db_session: AsyncSession, status: AttemptStatus
) -> None:
    env = await _env(client, db_session)
    await _seed_quiz(db_session, env.co.application_id, status=status)
    await _request_from_admin(client, env, env.reviewer_id)
    await _login(client, env.reviewer)
    resp = await client.get(_detail(env.co.application_id))
    assert resp.json()["quiz"] is None
    assert "Prompt" not in resp.text


@pytest.mark.usefixtures("migrated_db")
async def test_expired_quiz_has_a_summary(client: AsyncClient, db_session: AsyncSession) -> None:
    env = await _env(client, db_session)
    await _seed_quiz(db_session, env.co.application_id, status=AttemptStatus.EXPIRED)
    await _request_from_admin(client, env, env.reviewer_id)
    await _login(client, env.reviewer)
    resp = await client.get(_detail(env.co.application_id))
    assert resp.json()["quiz"]["total"] == 4


@pytest.mark.usefixtures("migrated_db")
async def test_no_quiz_is_null(client: AsyncClient, db_session: AsyncSession) -> None:
    env = await _env(client, db_session)
    await _request_from_admin(client, env, env.reviewer_id)
    await _login(client, env.reviewer)
    assert (await client.get(_detail(env.co.application_id))).json()["quiz"] is None


@pytest.mark.usefixtures("migrated_db", "bucket")
async def test_cv_url_is_presigned_and_none_without_a_cv(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    env = await _env(client, db_session)
    await _request_from_admin(client, env, env.reviewer_id)
    await _login(client, env.reviewer)
    url = _detail(env.co.application_id)
    application = await db_session.get(Application, UUID(env.co.application_id))
    assert application is not None
    assert application.cv_object_key in (await client.get(url)).json()["cv_url"]

    application.cv_object_key = ""
    await db_session.commit()
    resp = await client.get(url)
    assert resp.status_code == 200, resp.text
    assert resp.json()["cv_url"] is None


async def _access_rows(db: AsyncSession, application_id: str) -> list[AccessLog]:
    await db.rollback()
    return list(
        (
            await db.execute(
                select(AccessLog).where(AccessLog.application_id == UUID(application_id))
            )
        ).scalars()
    )


@pytest.mark.usefixtures("migrated_db")
async def test_detail_logs_access(client: AsyncClient, db_session: AsyncSession) -> None:
    env = await _env(client, db_session)
    other = await _second_application(db_session, env.co)
    await _request_from_admin(client, env, env.reviewer_id)
    await _login(client, env.reviewer)

    # refused reads and the list leave no row
    assert (await client.get(_detail(other))).status_code == 404
    assert await _access_rows(db_session, other) == []
    assert (await client.get(LIST_URL)).status_code == 200
    assert await _access_rows(db_session, env.co.application_id) == []

    assert (await client.get(_detail(env.co.application_id))).status_code == 200
    (row,) = await _access_rows(db_session, env.co.application_id)
    assert row.action == "view"
    assert row.actor_user_id == UUID(env.reviewer_id)

    # the helper's collapse window applies, same as the staff detail
    assert (await client.get(_detail(env.co.application_id))).status_code == 200
    assert len(await _access_rows(db_session, env.co.application_id)) == 1


@pytest.mark.usefixtures("migrated_db")
async def test_staff_cannot_use_review_list(client: AsyncClient, db_session: AsyncSession) -> None:
    env = await _env(client, db_session)
    for creds in (env.co.admin, env.co.member):
        await _login(client, creds)
        assert (await client.get(LIST_URL)).status_code == 403


@pytest.mark.usefixtures("migrated_db")
async def test_staff_open_detail_in_their_company_only(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    foreign = await _company(client, db_session)
    env = await _env(client, db_session)
    await _request_from_admin(client, env, env.co.member_id)
    await _login(client, env.co.member)
    await _submit(client, env.co)

    # an admin holds no row: the same shape, colleagues hidden as for anyone
    await _login(client, env.co.admin)
    resp = await client.get(_detail(env.co.application_id))
    assert resp.status_code == 200, resp.text
    assert resp.json()["mine"] is None
    assert resp.json()["others"] == []
    assert resp.json()["hidden_until_submitted"] is True
    assert (await client.get(_detail(foreign.application_id))).status_code == 404
    assert await _access_rows(db_session, foreign.application_id) == []


@pytest.mark.usefixtures("migrated_db")
async def test_promoted_reviewer_keeps_rows(client: AsyncClient, db_session: AsyncSession) -> None:
    env = await _env(client, db_session)
    await _request_from_admin(client, env, env.reviewer_id)
    resp = await client.patch(f"/api/v1/users/{env.reviewer_id}", json={"role": "member"})
    assert resp.status_code == 200, resp.text
    await _login(client, env.reviewer)
    assert len((await client.get("/api/v1/scorecards/mine")).json()) == 1
    assert (await client.get(LIST_URL)).status_code == 403


@pytest.mark.usefixtures("migrated_db")
async def test_unauthenticated_gets_401(client: AsyncClient, db_session: AsyncSession) -> None:
    env = await _env(client, db_session)
    await client.post("/api/v1/auth/logout")
    assert (await client.get(LIST_URL)).status_code == 401
    assert (await client.get(_detail(env.co.application_id))).status_code == 401


@pytest.mark.usefixtures("migrated_db")
async def test_list_query_count_does_not_grow(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    env = await _env(client, db_session)
    statements: list[str] = []

    def _count(_c: Any, _cur: Any, statement: str, *_rest: Any) -> None:
        statements.append(statement)

    async def _measure() -> int:
        await _login(client, env.reviewer)
        event.listen(Engine, "before_cursor_execute", _count)
        try:
            statements.clear()
            assert (await client.get(LIST_URL)).status_code == 200
            return len(statements)
        finally:
            event.remove(Engine, "before_cursor_execute", _count)

    await _request_from_admin(client, env, env.reviewer_id)
    one = await _measure()

    await _login(client, env.co.admin)
    for index in range(3):
        await _request(
            client,
            await _second_application(db_session, env.co, name=f"Person {index}"),
            env.reviewer_id,
        )
    four = await _measure()
    assert len((await client.get(LIST_URL)).json()) == 4
    assert four == one
