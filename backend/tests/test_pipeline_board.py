"""The open roles board: chips, counts, movement windows, sort (pipeline signals spec)."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models import (
    ActivityLog,
    Application,
    ApplicationStage,
    AttemptStatus,
    Candidate,
    Company,
    Interview,
    InterviewStatus,
    Job,
    JobStatus,
    QuizAttempt,
    User,
    UserRole,
)
from app.services import applications as applications_service
from app.services import pipeline_signals as signals
from app.services.activity import STAGE_CHANGED
from tests.db import database_reachable

pytestmark = pytest.mark.skipif(
    not database_reachable(), reason="database not reachable (start postgres or use CI)"
)

NOW = datetime(2026, 11, 10, 12, 0, tzinfo=UTC)


def days_ago(n: int) -> datetime:
    return NOW - timedelta(days=n)


@pytest.fixture
def multi_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "mode", "multi")


async def _company(db: AsyncSession, **settings_: object) -> Company:
    company = Company(slug=f"b-{uuid4().hex[:8]}", name="B Co", settings=dict(settings_))
    db.add(company)
    await db.flush()
    return company


async def _job(
    db: AsyncSession,
    company: Company,
    title: str = "Dev",
    *,
    status: JobStatus = JobStatus.PUBLISHED,
    published: int | None = 20,
    closed: int | None = None,
) -> Job:
    job = Job(
        company_id=company.id,
        slug=f"j-{uuid4().hex[:8]}",
        title=title,
        status=status,
        published_at=days_ago(published) if published is not None else None,
        closed_at=days_ago(closed) if closed is not None else None,
    )
    db.add(job)
    await db.flush()
    return job


async def _app(
    db: AsyncSession,
    job: Job,
    *,
    stage: ApplicationStage = ApplicationStage.SCREENING,
    created: int = 15,
    changed: int | None = None,
    moved: int | None = None,
) -> Application:
    """An application; `moved` days ago also gets a stage.changed activity row."""
    candidate = Candidate(
        company_id=job.company_id, email=f"c-{uuid4().hex[:8]}@x.dev", name="Marta"
    )
    db.add(candidate)
    await db.flush()
    application = Application(
        company_id=job.company_id,
        job_id=job.id,
        candidate_id=candidate.id,
        cv_object_key=f"cvs/{uuid4().hex}.pdf",
        cv_filename="cv.pdf",
        cv_size=1,
        stage=stage,
        stage_changed_at=days_ago(created if changed is None else changed),
    )
    application.created_at = days_ago(created)
    db.add(application)
    await db.flush()
    if moved is not None:
        db.add(
            ActivityLog(
                company_id=job.company_id,
                application_id=application.id,
                type=STAGE_CHANGED,
                payload={},
                created_at=days_ago(moved),
            )
        )
    await db.commit()
    return application


async def _board(db: AsyncSession, company: Company) -> signals.BoardOut:
    return await signals.board(db, company, now=NOW)


def _row(board: signals.BoardOut, job: Job) -> signals.BoardJob:
    return next(j for j in board.jobs if j.job_id == job.id)


async def test_published_job_without_live_is_empty_with_last_application_copy(
    db_session: AsyncSession,
) -> None:
    company = await _company(db_session)
    job = await _job(db_session, company)
    row = _row(await _board(db_session, company), job)
    assert row.status == "empty"
    assert row.reason == "No applications yet."
    assert row.days_open == 20

    await _app(db_session, job, stage=ApplicationStage.REJECTED, created=4)
    row = _row(await _board(db_session, company), job)
    assert row.status == "empty"
    assert row.reason == "No candidates in the pipeline. Last application 4 days ago."

    await _app(db_session, job, stage=ApplicationStage.REJECTED, created=1)
    row = _row(await _board(db_session, company), job)
    assert row.reason == "No candidates in the pipeline. Last application 1 day ago."


async def test_stalled_when_no_movement_for_limit_days(db_session: AsyncSession) -> None:
    company = await _company(db_session)
    job = await _job(db_session, company)
    await _app(db_session, job, created=15, moved=8)
    row = _row(await _board(db_session, company), job)
    assert row.status == "stalled"
    assert row.reason == "No candidate moved in the last 7 days. 1 waiting on you."
    assert row.last_movement_at == days_ago(8)
    assert row.moved_7d == 0

    # a movement inside the window clears it
    await _app(db_session, job, created=15, moved=6)
    assert _row(await _board(db_session, company), job).status != "stalled"


async def test_stalled_window_follows_the_limit_and_moved_7d_stays_seven(
    db_session: AsyncSession,
) -> None:
    company = await _company(db_session, stage_limit_days=14)
    job = await _job(db_session, company)
    await _app(db_session, job, created=30, changed=9, moved=9)
    row = _row(await _board(db_session, company), job)
    assert row.status != "stalled"  # 9 days is inside a 14 day window
    assert row.moved_7d == 0  # but outside the rolling 7 days
    assert row.last_movement_at == days_ago(9)


async def test_last_movement_is_not_bounded_by_a_window(db_session: AsyncSession) -> None:
    company = await _company(db_session)
    job = await _job(db_session, company)
    await _app(db_session, job, created=40, moved=33)
    row = _row(await _board(db_session, company), job)
    assert row.status == "stalled"
    assert row.last_movement_at == days_ago(33)


async def test_attention_when_one_overdue_and_movement_exists(db_session: AsyncSession) -> None:
    company = await _company(db_session)
    job = await _job(db_session, company)
    await _app(db_session, job, created=15, changed=9)  # waiting on team 9 days
    await _app(db_session, job, created=2, changed=2, moved=1)
    row = _row(await _board(db_session, company), job)
    assert row.status == "attention"
    assert row.overdue == 1
    assert row.waiting_on_team == 2
    assert row.longest_wait_days == 9
    assert row.reason == "1 candidate has waited on you for more than 7 days."

    await _app(db_session, job, created=15, changed=9)
    row = _row(await _board(db_session, company), job)
    assert row.reason == "2 candidates have waited on you for more than 7 days."


async def test_stalled_beats_attention(db_session: AsyncSession) -> None:
    company = await _company(db_session)
    job = await _job(db_session, company)
    await _app(db_session, job, created=15, changed=9, moved=9)
    row = _row(await _board(db_session, company), job)
    assert row.overdue == 1
    assert row.status == "stalled"


async def test_on_track_copy(db_session: AsyncSession) -> None:
    company = await _company(db_session)
    job = await _job(db_session, company)
    await _app(db_session, job, created=3, changed=1, moved=1)
    row = _row(await _board(db_session, company), job)
    assert row.status == "on_track"
    assert row.reason == "Candidates moved in the last 7 days and nobody is overdue."
    assert row.longest_wait_days == 1


async def test_limit_of_one_day_reads_in_the_singular(db_session: AsyncSession) -> None:
    company = await _company(db_session, stage_limit_days=1)
    job = await _job(db_session, company)
    await _app(db_session, job, created=15, moved=5)
    row = _row(await _board(db_session, company), job)
    assert row.reason == "No candidate moved in the last 1 day. 1 waiting on you."


async def test_closed_job_with_live_rows_is_on_board_days_open_frozen(
    db_session: AsyncSession,
) -> None:
    company = await _company(db_session)
    job = await _job(db_session, company, status=JobStatus.CLOSED, published=30, closed=10)
    await _app(db_session, job, created=15, moved=2)
    row = _row(await _board(db_session, company), job)
    assert row.job_status is JobStatus.CLOSED
    assert row.days_open == 20


async def test_closed_job_without_live_rows_absent_and_draft_absent(
    db_session: AsyncSession,
) -> None:
    company = await _company(db_session)
    closed = await _job(db_session, company, status=JobStatus.CLOSED, published=30, closed=10)
    await _app(db_session, closed, stage=ApplicationStage.HIRED, created=15)
    draft = await _job(db_session, company, status=JobStatus.DRAFT, published=None)
    await _app(db_session, draft, created=5)
    assert (await _board(db_session, company)).jobs == []


async def test_totals_equal_count_by_stage(db_session: AsyncSession) -> None:
    company = await _company(db_session)
    a = await _job(db_session, company, "A")
    b = await _job(db_session, company, "B", status=JobStatus.CLOSED, closed=3)
    for job, stage in [
        (a, ApplicationStage.NEW),
        (a, ApplicationStage.SCREENING),
        (a, ApplicationStage.SCREENING),
        (a, ApplicationStage.OFFER),
        (a, ApplicationStage.REJECTED),
        (b, ApplicationStage.INTERVIEW),
        (b, ApplicationStage.HIRED),
    ]:
        await _app(db_session, job, stage=stage, created=2)
    board = await _board(db_session, company)
    counted = await applications_service.count_by_stage(db_session, company)
    live_stages = ["new", "screening", "interview", "offer"]
    per_stage = {s: sum(getattr(j.live_by_stage, s) for j in board.jobs) for s in live_stages}
    assert per_stage == {s: counted.get(s, 0) for s in live_stages}
    assert board.totals.live == sum(per_stage.values()) == 5
    assert board.totals.active_jobs == 2
    assert board.stage_limit_days == 7


async def test_sort_order(db_session: AsyncSession) -> None:
    company = await _company(db_session)
    empty = await _job(db_session, company, "Aardvark")
    track = await _job(db_session, company, "Zed")
    stalled_b = await _job(db_session, company, "Bravo")
    stalled_a = await _job(db_session, company, "Alpha")
    stalled_over = await _job(db_session, company, "Charlie")
    attention = await _job(db_session, company, "Delta")
    await _app(db_session, track, created=3, changed=1, moved=1)
    await _app(db_session, stalled_b, created=15, changed=8, moved=8)
    await _app(db_session, stalled_a, created=15, changed=8, moved=8)
    await _app(db_session, stalled_over, created=15, changed=9, moved=9)
    await _app(db_session, stalled_over, created=15, changed=9, moved=9)
    await _app(db_session, attention, created=15, changed=9)
    await _app(db_session, attention, created=2, changed=1, moved=1)
    board = await _board(db_session, company)
    assert [j.title for j in board.jobs] == [
        "Charlie",
        "Alpha",
        "Bravo",
        "Delta",
        "Zed",
        empty.title,
    ]


async def test_new_7d_and_moved_7d_windows(db_session: AsyncSession) -> None:
    company = await _company(db_session)
    job = await _job(db_session, company)
    await _app(db_session, job, created=3, changed=3)  # new inside 7d
    await _app(db_session, job, created=8, changed=8)  # new outside
    await _app(db_session, job, stage=ApplicationStage.REJECTED, created=5)  # new, closed
    await _app(db_session, job, created=30, moved=6)  # moved inside
    await _app(db_session, job, created=30, moved=8)  # moved outside
    board = await _board(db_session, company)
    row = _row(board, job)
    assert row.new_7d == 2  # the 3 and 5 day old ones, rejected or not
    assert board.totals.new_7d == 2
    # the two new applications count as movement, plus the stage change 6 days ago
    assert row.moved_7d == 3


async def test_completed_quiz_counts_as_movement(db_session: AsyncSession) -> None:
    company = await _company(db_session)
    job = await _job(db_session, company)
    application = await _app(db_session, job, stage=ApplicationStage.NEW, created=15)
    db_session.add(
        QuizAttempt(
            company_id=company.id,
            application_id=application.id,
            status=AttemptStatus.COMPLETED,
            question_ids=["q1"],
            completed_at=days_ago(2),
            expires_at=NOW + timedelta(days=5),
        )
    )
    await db_session.commit()
    row = _row(await _board(db_session, company), job)
    assert row.status != "stalled"
    assert row.last_movement_at == days_ago(2)
    assert row.moved_7d == 1


async def _user(db: AsyncSession, company: Company) -> User:
    user = User(
        company_id=company.id,
        email=f"u-{uuid4().hex[:8]}@q.dev",
        password_hash="x",
        role=UserRole.ADMIN,
    )
    db.add(user)
    await db.flush()
    return user


async def test_cancelled_interview_is_ignored_waiting_on_team_since_stage_change(
    db_session: AsyncSession,
) -> None:
    company = await _company(db_session)
    job = await _job(db_session, company)
    user = await _user(db_session, company)
    application = await _app(
        db_session, job, stage=ApplicationStage.INTERVIEW, created=15, changed=9, moved=1
    )
    db_session.add(
        Interview(
            company_id=company.id,
            application_id=application.id,
            interviewer_user_id=user.id,
            duration_minutes=45,
            timezone="UTC",
            status=InterviewStatus.CANCELLED,
        )
    )
    await db_session.commit()
    live = await signals._load_live(db_session, company)
    assert [r.interview_view for r in live] == [None]
    row = _row(await _board(db_session, company), job)
    assert row.waiting_on_team == 1
    assert row.longest_wait_days == 9
    assert row.overdue == 1


async def test_pending_attempt_passes_through_as_a_candidate_wait(
    db_session: AsyncSession,
) -> None:
    company = await _company(db_session)
    job = await _job(db_session, company)
    application = await _app(
        db_session, job, stage=ApplicationStage.NEW, created=15, changed=15, moved=1
    )
    old = QuizAttempt(
        company_id=company.id,
        application_id=application.id,
        status=AttemptStatus.EXPIRED,
        question_ids=["q1"],
        expires_at=days_ago(10),
    )
    old.created_at = days_ago(14)
    newest = QuizAttempt(
        company_id=company.id,
        application_id=application.id,
        status=AttemptStatus.PENDING,
        question_ids=["q1"],
        expires_at=NOW + timedelta(days=3),
    )
    newest.created_at = days_ago(2)
    db_session.add_all([old, newest])
    await db_session.commit()
    live = await signals._load_live(db_session, company)
    view = live[0].attempt_view
    assert view is not None
    assert view.status is AttemptStatus.PENDING
    assert view.created_at == days_ago(2)
    row = _row(await _board(db_session, company), job)
    assert row.waiting_on_team == 0
    assert row.longest_wait_days is None
    assert row.overdue == 0


async def test_stalled_jobs_returns_only_stalled_rows(db_session: AsyncSession) -> None:
    company = await _company(db_session)
    stalled = await _job(db_session, company, "Stalled")
    fine = await _job(db_session, company, "Fine")
    await _app(db_session, stalled, created=15, moved=9)
    await _app(db_session, fine, created=3, changed=1, moved=1)
    rows = await signals.stalled_jobs(db_session, company, now=NOW)
    assert [r.job_id for r in rows] == [stalled.id]


async def test_other_company_rows_are_not_on_the_board(db_session: AsyncSession) -> None:
    mine = await _company(db_session)
    other = await _company(db_session)
    await _app(db_session, await _job(db_session, other), created=3)
    assert (await _board(db_session, mine)).jobs == []


async def _register(client: AsyncClient) -> None:
    resp = await client.post(
        "/api/v1/auth/register",
        json={
            "company_name": f"Board Co {uuid4().hex[:6]}",
            "email": f"admin-{uuid4().hex[:8]}@ganek-ci.dev",
            "password": "a-long-secure-password",
        },
    )
    assert resp.status_code == 201, resp.text


async def _make_user(client: AsyncClient, role: str) -> dict[str, str]:
    creds = {"email": f"{role}-{uuid4().hex[:8]}@ganek-ci.dev", "password": "member-password-1234"}
    resp = await client.post("/api/v1/users", json={**creds, "role": role})
    assert resp.status_code == 201, resp.text
    return creds


async def _login(client: AsyncClient, creds: dict[str, str]) -> None:
    await client.post("/api/v1/auth/logout")
    resp = await client.post("/api/v1/auth/login", json=creds)
    assert resp.status_code == 200, resp.text


@pytest.mark.usefixtures("migrated_db", "multi_mode")
async def test_route_reviewer_403_member_200(client: AsyncClient) -> None:
    await _register(client)
    job = (await client.post("/api/v1/jobs", json={"title": "Route role"})).json()
    assert (await client.post(f"/api/v1/jobs/{job['id']}/publish")).status_code == 200
    member = await _make_user(client, "member")
    reviewer = await _make_user(client, "reviewer")

    await _login(client, member)
    resp = await client.get("/api/v1/stats/board")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["stage_limit_days"] == 7
    assert [j["job_id"] for j in body["jobs"]] == [job["id"]]
    assert body["jobs"][0]["status"] == "empty"

    await _login(client, reviewer)
    assert (await client.get("/api/v1/stats/board")).status_code == 403
