"""arq job functions, called directly with a real DB session factory."""

import smtplib
from datetime import UTC, datetime, timedelta
from email.message import EmailMessage
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import settings
from app.models import (
    Application,
    AttemptStatus,
    Candidate,
    Company,
    Interview,
    InterviewStatus,
    Job,
    QuizAttempt,
    User,
    UserRole,
)
from app.worker import send_interview_reminder, send_quiz_nudge
from tests.db import database_reachable

pytestmark = pytest.mark.skipif(
    not database_reachable(), reason="database not reachable (start postgres or use CI)"
)


class FakeSMTP:
    sent: list[EmailMessage] = []

    def __init__(self, host: str, port: int, timeout: int) -> None: ...

    def __enter__(self) -> "FakeSMTP":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def starttls(self) -> None: ...

    def login(self, user: str, password: str) -> None: ...

    def send_message(self, message: EmailMessage) -> None:
        FakeSMTP.sent.append(message)


@pytest.fixture(autouse=True)
def _smtp(monkeypatch: pytest.MonkeyPatch) -> None:
    FakeSMTP.sent = []
    monkeypatch.setattr(settings, "smtp_host", "mail.example.com")
    monkeypatch.setattr(smtplib, "SMTP", FakeSMTP)


@pytest.fixture
async def ctx() -> Any:
    engine = create_async_engine(settings.database_url, poolclass=NullPool)
    yield {"session_factory": async_sessionmaker(engine, expire_on_commit=False)}
    await engine.dispose()


async def _booked_interview(db: AsyncSession, *, start: datetime) -> Interview:
    company = Company(slug=f"wk-{uuid4().hex[:8]}", name="Worker Co")
    db.add(company)
    await db.flush()
    job = Job(company_id=company.id, slug="backend-dev", title="Backend Dev")
    candidate = Candidate(
        company_id=company.id, email=f"cand-{uuid4().hex[:8]}@ganek-ci.dev", name="Marta"
    )
    interviewer = User(
        company_id=company.id,
        email=f"dana-{uuid4().hex[:8]}@wk.dev",
        password_hash="x",
        role=UserRole.MEMBER,
    )
    db.add_all([job, candidate, interviewer])
    await db.flush()
    application = Application(
        company_id=company.id,
        job_id=job.id,
        candidate_id=candidate.id,
        cv_object_key=f"cvs/{uuid4().hex}.pdf",
        cv_filename="cv.pdf",
        cv_size=1000,
    )
    db.add(application)
    await db.flush()
    interview = Interview(
        company_id=company.id,
        application_id=application.id,
        interviewer_user_id=interviewer.id,
        duration_minutes=45,
        timezone="Europe/Berlin",
        status=InterviewStatus.BOOKED,
        scheduled_start=start,
        meet_url="https://meet.google.com/abc",
    )
    db.add(interview)
    await db.commit()
    await db.refresh(interview)
    return interview


@pytest.mark.usefixtures("migrated_db")
async def test_reminder_sends_for_valid_booking(db_session: AsyncSession, ctx: Any) -> None:
    start = datetime.now(UTC) + timedelta(hours=20)
    interview = await _booked_interview(db_session, start=start)
    await send_interview_reminder(ctx, str(interview.id), start.isoformat())
    assert len(FakeSMTP.sent) == 1
    message = FakeSMTP.sent[0]
    assert "Reminder" in message["Subject"]
    plain = message.get_body(preferencelist=("plain",))
    assert plain is not None
    assert "https://meet.google.com/abc" in str(plain.get_content())


@pytest.mark.usefixtures("migrated_db")
async def test_reminder_noops_after_reschedule(db_session: AsyncSession, ctx: Any) -> None:
    start = datetime.now(UTC) + timedelta(hours=20)
    interview = await _booked_interview(db_session, start=start)
    stale = (start - timedelta(hours=3)).isoformat()  # job queued for the OLD slot
    await send_interview_reminder(ctx, str(interview.id), stale)
    assert FakeSMTP.sent == []


@pytest.mark.usefixtures("migrated_db")
async def test_reminder_noops_when_cancelled(db_session: AsyncSession, ctx: Any) -> None:
    start = datetime.now(UTC) + timedelta(hours=20)
    interview = await _booked_interview(db_session, start=start)
    interview.status = InterviewStatus.CANCELLED
    await db_session.commit()
    await send_interview_reminder(ctx, str(interview.id), start.isoformat())
    assert FakeSMTP.sent == []


async def _pending_attempt(db: AsyncSession, *, expires: datetime) -> QuizAttempt:
    company = Company(slug=f"wk-{uuid4().hex[:8]}", name="Nudge Co")
    db.add(company)
    await db.flush()
    job = Job(company_id=company.id, slug=f"role-{uuid4().hex[:6]}", title="Backend Dev")
    candidate = Candidate(
        company_id=company.id, email=f"cand-{uuid4().hex[:8]}@ganek-ci.dev", name="Marta"
    )
    db.add_all([job, candidate])
    await db.flush()
    application = Application(
        company_id=company.id,
        job_id=job.id,
        candidate_id=candidate.id,
        cv_object_key=f"cvs/{uuid4().hex}.pdf",
        cv_filename="cv.pdf",
        cv_size=1000,
    )
    db.add(application)
    await db.flush()
    attempt = QuizAttempt(
        company_id=company.id,
        application_id=application.id,
        status=AttemptStatus.PENDING,
        question_ids=["py-001", "py-002"],
        time_limit_seconds=60,
        expires_at=expires,
    )
    db.add(attempt)
    await db.commit()
    await db.refresh(attempt)
    return attempt


@pytest.mark.usefixtures("migrated_db")
async def test_quiz_nudge_sends_for_pending_attempt(db_session: AsyncSession, ctx: Any) -> None:
    """The nudge emails candidates unsupervised at night — it needs the same
    self-validation coverage as the interview reminder."""
    attempt = await _pending_attempt(db_session, expires=datetime.now(UTC) + timedelta(days=2))
    await send_quiz_nudge(ctx, str(attempt.id))
    assert len(FakeSMTP.sent) == 1
    message = FakeSMTP.sent[0]
    assert "expires" in message["Subject"]
    plain = message.get_body(preferencelist=("plain",))
    assert plain is not None
    assert "/quiz/" in str(plain.get_content())


@pytest.mark.usefixtures("migrated_db")
async def test_quiz_nudge_noops_when_no_longer_pending(db_session: AsyncSession, ctx: Any) -> None:
    attempt = await _pending_attempt(db_session, expires=datetime.now(UTC) + timedelta(days=2))
    attempt.status = AttemptStatus.COMPLETED
    await db_session.commit()
    await send_quiz_nudge(ctx, str(attempt.id))
    assert FakeSMTP.sent == []


@pytest.mark.usefixtures("migrated_db")
async def test_quiz_nudge_noops_when_already_expired(db_session: AsyncSession, ctx: Any) -> None:
    # nudging about a dead link would be worse than silence
    attempt = await _pending_attempt(db_session, expires=datetime.now(UTC) - timedelta(hours=1))
    await send_quiz_nudge(ctx, str(attempt.id))
    assert FakeSMTP.sent == []


async def test_enqueue_survives_missing_redis(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core import queue

    monkeypatch.setattr(settings, "redis_url", "redis://localhost:1/0")  # nothing listens
    queue._pool = None
    queue._last_failure = None
    assert (
        await queue.enqueue("send_quiz_nudge", "x", defer_until=datetime.now(UTC), job_id="j1")
        is False
    )


async def test_enqueue_circuit_breaker_skips_after_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.core import queue

    monkeypatch.setattr(settings, "redis_url", "redis://localhost:1/0")
    queue._pool = None
    queue._last_failure = None
    assert await queue.enqueue("send_quiz_nudge", "x") is False
    assert queue._last_failure is not None
    # within the backoff window the second call returns instantly
    assert await queue.enqueue("send_quiz_nudge", "y") is False
