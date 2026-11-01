"""Reports loader and route: cohort windows, job filter, sources, quiz line,
reconciliation with the applicants page counts."""

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models import (
    ActivityLog,
    Application,
    ApplicationStage,
    AttemptStatus,
    Candidate,
    Company,
    Job,
    JobStatus,
    QuizAttempt,
)
from app.schemas.stats import Period, ReportsOut
from app.services import reports
from app.services.activity import STAGE_CHANGED
from tests.db import database_reachable

pytestmark = pytest.mark.skipif(
    not database_reachable(), reason="database not reachable (start postgres or use CI)"
)

S = ApplicationStage
NOW = datetime(2026, 11, 10, 12, 0, tzinfo=UTC)


def days_ago(n: int) -> datetime:
    return NOW - timedelta(days=n)


@pytest.fixture
def multi_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "mode", "multi")


async def _company(db: AsyncSession) -> Company:
    company = Company(slug=f"r-{uuid4().hex[:8]}", name="R Co")
    db.add(company)
    await db.flush()
    return company


async def _job(db: AsyncSession, company: Company, title: str = "Dev") -> Job:
    job = Job(
        company_id=company.id,
        slug=f"j-{uuid4().hex[:8]}",
        title=title,
        status=JobStatus.PUBLISHED,
        published_at=days_ago(100),
    )
    db.add(job)
    await db.flush()
    return job


async def _app(
    db: AsyncSession,
    job: Job,
    *,
    stage: S = S.NEW,
    created: datetime | int = 5,
    moves: tuple[tuple[int, S | None, S], ...] = (),
    source: str | None = None,
    changed: int | None = None,
) -> Application:
    """An application created `created` days ago (or at a moment); `moves` are
    (days ago, from, to) stage.changed rows."""
    candidate = Candidate(
        company_id=job.company_id, email=f"c-{uuid4().hex[:8]}@x.dev", name="Marta"
    )
    db.add(candidate)
    await db.flush()
    created_at = days_ago(created) if isinstance(created, int) else created
    application = Application(
        company_id=job.company_id,
        job_id=job.id,
        candidate_id=candidate.id,
        cv_object_key=f"cvs/{uuid4().hex}.pdf",
        cv_filename="cv.pdf",
        cv_size=1,
        stage=stage,
        stage_changed_at=days_ago(changed) if changed is not None else created_at,
        source=source,
    )
    application.created_at = created_at
    db.add(application)
    await db.flush()
    for when, from_stage, to_stage in moves:
        db.add(
            ActivityLog(
                company_id=job.company_id,
                application_id=application.id,
                type=STAGE_CHANGED,
                payload={
                    **({"from": from_stage.value} if from_stage else {}),
                    "to": to_stage.value,
                },
                created_at=days_ago(when),
            )
        )
    await db.commit()
    return application


async def _report(
    db: AsyncSession, company: Company, period: Period = "90d", job: Job | None = None
) -> ReportsOut:
    return await reports.reports(
        db, company, period=period, job_id=job.id if job else None, now=NOW
    )


async def test_period_cohort_and_previous_deltas(db_session: AsyncSession) -> None:
    company = await _company(db_session)
    job = await _job(db_session, company)
    start = datetime(2026, 10, 12, tzinfo=UTC)  # 30d window start (inclusive)
    await _app(db_session, job, created=start)  # exactly at the start: current
    await _app(db_session, job, created=start - timedelta(seconds=1))  # previous
    await _app(db_session, job, created=start - timedelta(days=30))  # previous, lower edge
    await _app(db_session, job, created=start - timedelta(days=30, seconds=1))  # before both
    await _app(db_session, job, created=3)

    report = await _report(db_session, company, "30d")
    assert report.cohort.applications == 2
    assert report.previous is not None
    assert report.previous.applications == 2
    assert report.period == "30d"


async def test_all_has_no_previous_and_counts_everything(db_session: AsyncSession) -> None:
    company = await _company(db_session)
    job = await _job(db_session, company)
    await _app(db_session, job, created=900)
    await _app(db_session, job, created=2)
    report = await _report(db_session, company, "all")
    assert report.previous is None
    assert report.cohort.applications == 2
    assert len(report.weekly) == 53


async def test_job_filter(db_session: AsyncSession) -> None:
    company = await _company(db_session)
    first, second = await _job(db_session, company), await _job(db_session, company)
    await _app(db_session, first, stage=S.SCREENING, created=40, changed=20)
    await _app(db_session, second, stage=S.INTERVIEW, created=40, changed=3)
    await _app(db_session, second, stage=S.REJECTED, created=40)
    report = await _report(db_session, company, "all", first)
    assert report.job_id == first.id
    assert report.cohort.applications == 1
    assert report.time_in_stage[1].oldest_live_days == 20  # screening, only this job
    assert report.time_in_stage[2].oldest_live_days is None
    assert [s.still_here for s in report.funnel] == [0, 1, 0, 0, 0]


async def test_oldest_live_uses_the_cohort(db_session: AsyncSession) -> None:
    company = await _company(db_session)
    job = await _job(db_session, company)
    await _app(db_session, job, stage=S.SCREENING, created=200, changed=150)  # outside 30d
    await _app(db_session, job, stage=S.SCREENING, created=10, changed=4)
    report = await _report(db_session, company, "30d")
    assert report.time_in_stage[1].oldest_live_days == 4


async def test_sources_null_is_direct_sorted(db_session: AsyncSession) -> None:
    company = await _company(db_session)
    job = await _job(db_session, company)
    await _app(db_session, job, source="linkedin")
    await _app(db_session, job, source=None)
    await _app(db_session, job, source=None, stage=S.INTERVIEW, moves=((3, S.NEW, S.INTERVIEW),))
    report = await _report(db_session, company)
    assert [(s.source, s.applications, s.reached_interview) for s in report.sources] == [
        ("direct", 2, 1),
        ("linkedin", 1, 0),
    ]


async def _attempt(
    db: AsyncSession,
    application: Application,
    status: AttemptStatus,
    expires_in_days: int = 7,
) -> None:
    db.add(
        QuizAttempt(
            company_id=application.company_id,
            application_id=application.id,
            status=status,
            question_ids=["q1"],
            time_limit_seconds=None,
            expires_at=NOW + timedelta(days=expires_in_days),
        )
    )
    await db.commit()


async def test_quiz_line_excludes_invalidated(db_session: AsyncSession) -> None:
    company = await _company(db_session)
    job = await _job(db_session, company)
    application = await _app(db_session, job)
    for status in (
        AttemptStatus.INVALIDATED,
        AttemptStatus.COMPLETED,
        AttemptStatus.EXPIRED,
        AttemptStatus.PENDING,
    ):
        await _attempt(db_session, application, status)
    old = await _app(db_session, job, created=400)
    await _attempt(db_session, old, AttemptStatus.COMPLETED)
    report = await _report(db_session, company, "90d")
    assert (report.quiz.invited, report.quiz.completed, report.quiz.expired) == (3, 1, 1)
    assert report.quiz_scores.attempts_total == 3  # same cohort and exclusion


async def test_quiz_line_counts_a_lapsed_pending_invite_as_expired(
    db_session: AsyncSession,
) -> None:
    company = await _company(db_session)
    job = await _job(db_session, company)
    application = await _app(db_session, job)
    await _attempt(db_session, application, AttemptStatus.PENDING, expires_in_days=-1)
    await _attempt(db_session, application, AttemptStatus.PENDING, expires_in_days=2)
    await _attempt(db_session, application, AttemptStatus.EXPIRED)
    report = await _report(db_session, company, "90d")
    assert (report.quiz.invited, report.quiz.expired) == (3, 2)


async def test_previous_median_below_three_is_none(db_session: AsyncSession) -> None:
    company = await _company(db_session)
    job = await _job(db_session, company)
    for age in (40, 45):  # previous 30d window: two hires
        await _app(
            db_session,
            job,
            stage=S.HIRED,
            created=age,
            moves=((age - 10, S.OFFER, S.HIRED),),
        )
    for age in (20, 21, 22):  # current window: three hires
        await _app(
            db_session, job, stage=S.HIRED, created=age, moves=((age - 5, S.OFFER, S.HIRED),)
        )
    report = await _report(db_session, company, "30d")
    assert report.cohort.median_time_to_hire_days == 5.0
    assert report.cohort.hires_n == 3
    assert report.previous is not None
    assert report.previous.hires == 2
    assert report.previous.median_time_to_hire_days is None


async def test_time_in_stage_and_funnel_from_history(db_session: AsyncSession) -> None:
    company = await _company(db_session)
    job = await _job(db_session, company)
    for _ in range(3):
        await _app(
            db_session,
            job,
            stage=S.INTERVIEW,
            created=20,
            changed=10,
            moves=((18, S.NEW, S.SCREENING), (10, S.SCREENING, S.INTERVIEW)),
        )
    await _app(
        db_session,
        job,
        stage=S.WITHDRAWN,
        created=20,
        moves=((9, S.INTERVIEW, S.REJECTED), (8, S.REJECTED, S.WITHDRAWN)),
    )
    report = await _report(db_session, company, "all")
    assert report.time_in_stage[0].median_days == 2.0 and report.time_in_stage[0].n == 3
    assert report.time_in_stage[1].median_days == 8.0
    assert report.funnel[2].withdrawn_from == 1  # walked back past the held rejection
    assert report.diagnosis == ["Not enough data yet (4 applications)"]


async def test_other_company_is_excluded(db_session: AsyncSession) -> None:
    mine, other = await _company(db_session), await _company(db_session)
    await _app(db_session, await _job(db_session, other), moves=((2, S.NEW, S.SCREENING),))
    await _app(db_session, await _job(db_session, mine))
    report = await _report(db_session, mine, "all")
    assert report.cohort.applications == 1
    assert report.funnel[1].reached == 0


async def _register(client: AsyncClient) -> str:
    name = f"Reports Co {uuid4().hex[:6]}"
    resp = await client.post(
        "/api/v1/auth/register",
        json={
            "company_name": name,
            "email": f"admin-{uuid4().hex[:8]}@ganek-ci.dev",
            "password": "a-long-secure-password",
        },
    )
    assert resp.status_code == 201, resp.text
    return name


@pytest.mark.usefixtures("migrated_db", "multi_mode")
async def test_reports_reconcile_with_count_by_stage_for_all(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    name = await _register(client)
    company = (await db_session.execute(select(Company).where(Company.name == name))).scalar_one()
    job = await _job(db_session, company)
    plan = [
        S.NEW,
        S.NEW,
        S.SCREENING,
        S.INTERVIEW,
        S.INTERVIEW,
        S.OFFER,
        S.HIRED,
        S.REJECTED,
        S.WITHDRAWN,
    ]
    for stage in plan:
        await _app(
            db_session,
            job,
            stage=stage,
            created=datetime.now(UTC) - timedelta(days=7),  # the route reads the real clock
            moves=((6, S.NEW, stage),),
        )

    page = (await client.get("/api/v1/applications")).json()
    resp = await client.get("/api/v1/stats/reports", params={"period": "all"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["cohort"]["applications"] == page["total"] == len(plan)
    still_here = {step["stage"]: step["still_here"] for step in body["funnel"]}
    for name_ in ("new", "screening", "interview", "offer"):
        assert still_here[name_] == page["stage_counts"].get(name_, 0)
    assert body["previous"] is None
    assert body["funnel"][4]["still_here"] == 0

    default = (await client.get("/api/v1/stats/reports")).json()
    assert default["period"] == "90d"


@pytest.mark.usefixtures("migrated_db", "multi_mode")
async def test_reviewer_403(client: AsyncClient) -> None:
    await _register(client)
    creds = {"email": f"rev-{uuid4().hex[:8]}@ganek-ci.dev", "password": "member-password-1234"}
    resp = await client.post("/api/v1/users", json={**creds, "role": "reviewer"})
    assert resp.status_code == 201, resp.text
    await client.post("/api/v1/auth/logout")
    assert (await client.post("/api/v1/auth/login", json=creds)).status_code == 200
    assert (await client.get("/api/v1/stats/reports")).status_code == 403
    job_id = UUID(int=1)
    assert (
        await client.get("/api/v1/stats/reports", params={"job_id": str(job_id)})
    ).status_code == 403
