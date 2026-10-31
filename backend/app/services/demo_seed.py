"""Demo workspace: ACME Ganek, for local dev, screenshots and the
public demo instance.

Everything goes through the real service layer (jobs, applications, the
quiz engine), so the dashboard, stats, activity feed and queue look the
way a lived-in workspace looks. Deterministic: the same slug and seed
build the same workspace. Idempotent: an existing company is left alone
unless ``reset`` is set, which deletes it (cascade) and its CV objects
first.

Run inside the backend image, like the question bank seed::

    uv run python -m app.services.demo_seed [--reset] [--slug acme]

The password comes from GANEK_DEMO_PASSWORD (default ``ganek-demo-1``). A public
demo instance sets GANEK_DEMO_RESET_SLUG and the worker reruns this with
``reset=True`` every night (app/worker.py).
Every person in here is fictional; candidate addresses end in
``@example.com`` so no mail can ever reach a real inbox.
"""

import argparse
import asyncio
import logging
import os
import random
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import urls
from app.core.config import settings
from app.core.db import SessionFactory
from app.core.security import hash_password
from app.models import (
    ActivityLog,
    Application,
    ApplicationNote,
    ApplicationStage,
    AttemptAnswer,
    Company,
    EmailOutbox,
    EmailStatus,
    Job,
    JobView,
    QuizAttempt,
    User,
    UserRole,
)
from app.schemas.jobs import JobCreate, QuizConfigSchema
from app.schemas.public import ApplicationSubmit
from app.services import activity, email_render, storage
from app.services import applications as applications_service
from app.services import company as company_service
from app.services import jobs as jobs_service
from app.services import quiz as quiz_service
from app.services.email_templates import PREVIEW_LINK_PLACEHOLDER

logger = logging.getLogger(__name__)

DEFAULT_SLUG = "acme"
DEFAULT_PASSWORD = "ganek-demo-1"  # noqa: S105 (demo credential, documented)
RNG_SEED = 20260830
BRAND_PRIMARY = "#6d28d9"

# the smallest thing MinIO will store as a PDF and the CV check will accept
PDF_BYTES = (
    b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
    b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
    b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 595 842]>>endobj\n"
    b"trailer<</Root 1 0 R>>\n%%EOF\n"
)


@dataclass(frozen=True)
class SeedResult:
    created: bool
    company_id: uuid.UUID
    applications: int = 0
    attempts: int = 0
    views: int = 0


@dataclass(frozen=True)
class _Job:
    title: str
    location: str
    tags: list[str]
    quiz_questions: int | None  # None = no quiz on this job
    description_md: str
    salary: tuple[int, int] | None = None


JOBS = (
    _Job(
        "Backend Engineer (Python)",
        "Berlin",
        ["python", "fastapi", "sql"],
        8,
        "## About the role\n\nYou own the services behind our fleet telemetry: FastAPI, "
        "PostgreSQL, a worker queue, and the kind of data volumes a few thousand robots "
        "produce.\n\n## What we look for\n\n- Solid Python and SQL\n- You have run "
        "something in production and been paged for it\n- You write things down",
        (65_000, 85_000),
    ),
    _Job(
        "Site Reliability Engineer",
        "Berlin or remote (EU)",
        ["devops", "sql"],
        None,
        "## About the role\n\nKeep the control plane boring: observability, on-call "
        "rotations, capacity. Kubernetes on bare metal, Postgres, a lot of Grafana.",
        (70_000, 90_000),
    ),
    _Job(
        "Product Designer",
        "Berlin",
        ["frontend"],
        None,
        "## About the role\n\nDesign the operator console our customers run their "
        "warehouses from. Research, flows, a design system that engineers like.",
        None,
    ),
    _Job(
        "Senior Frontend Engineer",
        "Remote (EU)",
        ["react", "typescript", "javascript"],
        None,
        "## About the role\n\nReact and TypeScript on a real-time fleet map. You care "
        "about rendering performance and accessibility in equal measure.",
        (75_000, 95_000),
    ),
)


@dataclass(frozen=True)
class _Candidate:
    name: str
    job: int  # index into JOBS
    correct: int | None = None  # quiz answers right out of 8; None = quiz not taken
    stage: ApplicationStage = ApplicationStage.NEW
    github: str | None = None
    linkedin: str | None = None
    message: str | None = None
    flag: str | None = None  # "blur" or "fast": the two integrity stories
    source: str = "direct"  # where they came from (core/sources.py grammar)


CANDIDATES = (
    _Candidate(
        "Mia Okafor",
        0,
        7,
        ApplicationStage.INTERVIEW,
        github="https://github.com/Ganek-dev",
        message="I ran the ingestion pipeline at a logistics startup for three years.",
        source="linkedin",
    ),
    _Candidate("Alex Brandt", 0, 7, ApplicationStage.SCREENING, flag="blur", source="google"),
    _Candidate("Karol Zielinski", 0, 6, ApplicationStage.INTERVIEW),  # direct
    _Candidate(
        "Hanna Bergstrom",
        0,
        6,
        ApplicationStage.SCREENING,
        linkedin="https://www.linkedin.com/company/ganek-io",
        source="linkedin",
    ),
    _Candidate("Diego Alvarez", 0, 5, ApplicationStage.SCREENING, source="link:newsletter"),
    _Candidate("Nina Lindqvist", 0, 5, ApplicationStage.NEW, source="google"),
    _Candidate("Pavel Horak", 0, 4, ApplicationStage.SCREENING, source="linkedin"),
    _Candidate("Sofia Ricci", 0, 4, ApplicationStage.NEW, source="ref:robotics-weekly.example"),
    _Candidate("Lucas Moreau", 0, 3, ApplicationStage.REJECTED),  # direct
    _Candidate("Aisha Khan", 0, 3, ApplicationStage.NEW, flag="fast", source="linkedin"),
    _Candidate("Tomas Ferreira", 0, 2, ApplicationStage.REJECTED, source="google"),
    _Candidate("Ingrid Solberg", 0, None, ApplicationStage.NEW, source="link:newsletter"),  # open
    _Candidate("Marek Novak", 0, None, ApplicationStage.NEW, source="hn"),
    _Candidate("Yuki Tanaka", 0, None, ApplicationStage.REJECTED),  # direct
    _Candidate("Lena Fischer", 3, None, ApplicationStage.SCREENING, source="linkedin"),
    _Candidate("Omar Haddad", 3, None, ApplicationStage.NEW),  # direct
    _Candidate("Chloe Martin", 1, None, ApplicationStage.NEW, source="indeed"),
)

# Page views per job and day (spec job posts v2 5.5), by source, for the last
# 30 days: base loads per weekday, a share per source, and one newsletter
# send ten days ago that shows as a spike. Shares sum to 1.
VIEW_BASE_PER_JOB = (28, 14, 10, 18)  # index into JOBS
VIEW_SHARES = (
    ("direct", 0.30),
    ("linkedin", 0.25),
    ("google", 0.18),
    ("indeed", 0.08),
    ("link:newsletter", 0.07),
    ("website", 0.05),
    ("hn", 0.04),
    ("ref:robotics-weekly.example", 0.03),
)
NEWSLETTER_DAYS_AGO = 10
VIEW_DAYS = 30

NOTES = (
    (0, "erika", "Strong on the pipeline questions. Pair her with Jonas for the systems round."),
    (2, "jonas", "Asked good questions about on-call. Check notice period before the offer talk."),
)


def _email(name: str) -> str:
    return name.lower().replace(" ", ".") + "@example.com"


async def _existing(db: AsyncSession, slug: str) -> Company | None:
    return (await db.execute(select(Company).where(Company.slug == slug))).scalar_one_or_none()


async def _remove(db: AsyncSession, company: Company) -> None:
    """Delete the demo company and the CV objects only its rows point to."""
    keys = (
        await db.execute(
            select(Application.cv_object_key).where(Application.company_id == company.id)
        )
    ).scalars()
    for key in keys:
        if key:
            await storage.delete_object(key)
    # a core DELETE: the ORM would first null out loaded children's FKs,
    # the database cascades (every tenant table is ON DELETE CASCADE) do it right
    await db.execute(delete(Company).where(Company.id == company.id))
    await db.commit()
    db.expunge_all()


def _wrong_key(question_options: dict[str, object], correct_key: str, rng: random.Random) -> str:
    return rng.choice([key for key in question_options if key != correct_key])


async def _take_quiz(
    db: AsyncSession,
    company: Company,
    application: Application,
    job: Job,
    spec: _Candidate,
    rng: random.Random,
) -> QuizAttempt | None:
    attempt = await quiz_service.create_attempt(db, company, application, job, rng=rng)
    if attempt is None or spec.correct is None:
        return attempt
    total = len(attempt.question_ids)
    plan = [True] * spec.correct + [False] * (total - spec.correct)
    rng.shuffle(plan)
    # answered in seconds, not milliseconds; the "fast" story sits just under 3 s
    pace = (2.2, 2.9) if spec.flag == "fast" else (5.0, 17.0)
    for index, right in enumerate(plan):
        served = await quiz_service.current_or_next_question(db, attempt, rng=rng)
        assert served is not None, "the engine served fewer questions than planned"
        answer, question = served
        if spec.flag == "blur" and index in (2, 4):
            await quiz_service.record_events(
                db,
                attempt,
                [
                    {
                        "type": "blur",
                        "duration_ms": 12_000 if index == 2 else 27_000,
                        "question_id": question.id,
                    }
                ],
            )
        key = (
            question.correct_key
            if right
            else _wrong_key(question.options, question.correct_key, rng)
        )
        await quiz_service.submit_answer(db, attempt, question.id, key)
    await _humanize_pace(db, attempt, pace, rng)
    finished = await quiz_service.current_or_next_question(db, attempt, rng=rng)
    assert finished is None, "the quiz should be complete"
    await db.refresh(attempt)
    return attempt


async def _humanize_pace(
    db: AsyncSession, attempt: QuizAttempt, pace: tuple[float, float], rng: random.Random
) -> None:
    """The engine stamps served_at and answered_at a few ms apart. Stretch
    every gap into a human response time before the flags are computed,
    walking back from the last answer so served_at stays in the order the
    questions were taken: the review page numbers Q1..Qn by that order, and
    shifting each answer on its own used to scramble it (blurs recorded on
    the third and fifth question read "Q1 and Q6" in the event log)."""
    answers = await quiz_service.resolved_answers(db, attempt)
    assert answers and all(a.answered_at is not None for a in answers)
    clock = answers[-1].answered_at
    assert clock is not None
    for recorded in reversed(answers):
        recorded.answered_at = clock
        recorded.served_at = clock - timedelta(seconds=rng.uniform(*pace))
        recorded.deadline_at = recorded.served_at + timedelta(seconds=22)
        clock = recorded.served_at - timedelta(seconds=rng.uniform(0.5, 2.0))
    attempt.started_at = answers[0].served_at
    await db.commit()


async def _backdate(db: AsyncSession, application: Application, offset: timedelta) -> None:
    """Shift everything about one application into the past by ``offset``."""
    # stage_changed_at is a server default: load it before shifting, or the
    # stamp stays at seed time and the panel reads "moved to new just now".
    await db.refresh(application, ["stage_changed_at"])
    application.created_at -= offset
    application.stage_changed_at -= offset
    if application.decided_at is not None:
        application.decided_at -= offset
    attempts = (
        (await db.execute(select(QuizAttempt).where(QuizAttempt.application_id == application.id)))
        .scalars()
        .all()
    )
    for attempt in attempts:
        attempt.created_at -= offset
        attempt.expires_at -= offset
        if attempt.started_at is not None:
            attempt.started_at -= offset
        if attempt.completed_at is not None:
            attempt.completed_at -= offset
        answers = (
            (await db.execute(select(AttemptAnswer).where(AttemptAnswer.attempt_id == attempt.id)))
            .scalars()
            .all()
        )
        for answer in answers:
            answer.served_at -= offset
            answer.deadline_at -= offset
            if answer.answered_at is not None:
                answer.answered_at -= offset
    events = (
        await db.execute(select(ActivityLog).where(ActivityLog.application_id == application.id))
    ).scalars()
    for event in events:
        event.created_at -= offset
    notes = (
        await db.execute(
            select(ApplicationNote).where(ApplicationNote.application_id == application.id)
        )
    ).scalars()
    for note in notes:
        note.created_at -= offset
    await db.commit()


async def seed(
    db: AsyncSession,
    *,
    slug: str = DEFAULT_SLUG,
    password: str = DEFAULT_PASSWORD,
    reset: bool = False,
    rng_seed: int = RNG_SEED,
) -> SeedResult:
    existing = await _existing(db, slug)
    if existing is not None:
        if not reset:
            return SeedResult(created=False, company_id=existing.id)
        await _remove(db, existing)

    rng = random.Random(rng_seed)  # noqa: S311 (fixture data, not security)
    domain = f"{slug}.example"
    company = Company(
        slug=slug,
        name="ACME Ganek",
        description=(
            "Fictional demo company. ACME Ganek builds autonomous warehouse robots and "
            "the software that runs them. "
            "Berlin, 60 people, hardware and software under one roof."
        ),
        website=f"https://{domain}",
        socials={"github": "https://github.com/Ganek-dev"},
        theme={"primary_color": BRAND_PRIMARY},
        settings={
            "legal_name": "ACME Ganek GmbH",
            "contact_email": f"privacy@{domain}",
            "quiz_expired_reissue": "auto",
        },
    )
    db.add(company)
    await db.flush()
    erika = User(
        company_id=company.id,
        email=f"erika@{domain}",
        password_hash=hash_password(password),
        role=UserRole.ADMIN,
        is_active=True,
        display_name="Erika",
    )
    jonas = User(
        company_id=company.id,
        email=f"jonas@{domain}",
        password_hash=hash_password(password),
        role=UserRole.MEMBER,
        is_active=True,
        display_name="Jonas",
    )
    db.add_all([erika, jonas])
    await db.commit()
    authors = {"erika": erika, "jonas": jonas}

    jobs: list[Job] = []
    for spec in JOBS:
        job = await jobs_service.create_job(
            db,
            company,
            JobCreate(
                title=spec.title,
                description_md=spec.description_md,
                location=spec.location,
                tags=spec.tags,
                salary_min=spec.salary[0] if spec.salary else None,
                salary_max=spec.salary[1] if spec.salary else None,
                salary_currency="EUR" if spec.salary else None,
                quiz_config=QuizConfigSchema(
                    enabled=spec.quiz_questions is not None,
                    question_count=spec.quiz_questions or 6,
                    time_limit_seconds=20,
                ),
            ),
        )
        jobs.append(await jobs_service.publish_job(db, job))

    applications: list[Application] = []
    attempts = 0
    for index, cand in enumerate(CANDIDATES):
        job = jobs[cand.job]
        key = storage.build_cv_key(company.id)
        await storage.put_object(key, PDF_BYTES, storage.CV_CONTENT_TYPE)
        application = await applications_service.submit_application(
            db,
            company,
            job,
            ApplicationSubmit(
                name=cand.name,
                email=_email(cand.name),
                message=cand.message,
                github=cand.github,
                linkedin=cand.linkedin,
                cv_object_key=key,
                cv_filename=f"{cand.name.split()[-1].lower()}-cv.pdf",
                source=cand.source,
            ),
        )
        attempt = await _take_quiz(db, company, application, job, cand, rng)
        if attempt is not None and cand.correct is not None:
            attempts += 1
        if cand.stage is not ApplicationStage.NEW:
            application = await applications_service.set_stage(
                db, application, cand.stage, actor_user_id=erika.id
            )
        applications.append(application)
        for note_index, author, body in NOTES:
            if note_index == index:
                db.add(
                    ApplicationNote(
                        company_id=company.id,
                        application_id=application.id,
                        author_user_id=authors[author].id,
                        body=body,
                    )
                )
                activity.record(
                    db,
                    company_id=company.id,
                    type=activity.NOTE_ADDED,
                    actor_user_id=authors[author].id,
                    application_id=application.id,
                    payload={},
                )
                await db.commit()
        # oldest applicants first in the list, the newest a few hours ago
        days_ago = 20.0 - index * (19.0 / max(1, len(CANDIDATES) - 1)) + rng.uniform(-0.3, 0.3)
        await _backdate(db, application, timedelta(days=max(0.1, days_ago)))
        await _seed_sent_mail(db, company, application, job, cand.stage)

    views = await _seed_views(db, jobs, rng)
    return SeedResult(
        created=True,
        company_id=company.id,
        applications=len(applications),
        attempts=attempts,
        views=views,
    )


_MAIL_KIND_FOR_STAGE = {
    ApplicationStage.INTERVIEW: "stage_advance",
    ApplicationStage.REJECTED: "rejection",
}


async def _seed_sent_mail(
    db: AsyncSession, company: Company, application: Application, job: Job, stage: ApplicationStage
) -> None:
    """One delivered stage mail per interview or rejected applicant, rendered
    from the built-in template, so the demo timeline shows a subject and the
    text (PR 4). A demo instance never mails, so the rows are written here.
    The links carry the preview placeholder, never a real token."""
    kind = _MAIL_KIND_FOR_STAGE.get(stage)
    if kind is None:
        return
    await db.refresh(application, ["candidate", "quiz_attempts", "stage_changed_at"])
    context: dict[str, Any] = {
        "candidate_name": application.candidate.name,
        "job_title": job.title,
        "company_name": company.name,
        "controller_name": company_service.controller_name(company),
        "privacy_url": urls.privacy_notice_url(company),
    }
    if kind == "stage_advance":
        context.update(
            brand_primary=(company.theme or {}).get("primary_color"),
            status_url=urls.status_url(company, PREVIEW_LINK_PLACEHOLDER),
        )
    else:
        attempt = application.quiz_attempt
        context.update(
            careers_url=urls.careers_url(company),
            completed_assessment=attempt is not None and attempt.completed_at is not None,
        )
    rendered = email_render.render(kind, email_render.BUILTIN[kind], context)
    sent_at = application.stage_changed_at + timedelta(minutes=1)
    db.add(
        EmailOutbox(
            company_id=company.id,
            application_id=application.id,
            kind=kind,
            payload={"to": application.candidate.email, "ref": str(application.id), **context},
            status=EmailStatus.SENT,
            attempts=1,
            created_at=sent_at,
            sent_at=sent_at,
            rendered_subject=rendered.subject,
            rendered_text=rendered.text,
        )
    )
    await db.commit()


async def _seed_views(db: AsyncSession, jobs: list[Job], rng: random.Random) -> int:
    """Daily page-view totals per job and source for the last VIEW_DAYS days,
    so the overview's tiles, chart, Sources table and apply rates look like
    a careers page people actually open. Aggregates only, like the real
    counter: no visitor exists behind these numbers."""
    today = datetime.now(UTC).date()
    total = 0
    rows: list[JobView] = []
    for job, base in zip(jobs, VIEW_BASE_PER_JOB, strict=True):
        for days_ago in range(VIEW_DAYS):
            day = today - timedelta(days=days_ago)
            weekend = 0.45 if day.weekday() >= 5 else 1.0
            daily = base * weekend * rng.uniform(0.75, 1.25)
            for source, share in VIEW_SHARES:
                views = round(daily * share * rng.uniform(0.6, 1.4))
                if source == "link:newsletter" and days_ago == NEWSLETTER_DAYS_AGO:
                    views += round(base * 1.5)
                if source in ("direct", "linkedin", "google"):
                    views = max(1, views)
                if views > 0:
                    rows.append(JobView(job_id=job.id, day=day, source=source, views=views))
                    total += views
    db.add_all(rows)
    await db.commit()
    return total


async def run(*, slug: str, password: str, reset: bool) -> None:
    async with SessionFactory() as db:
        result = await seed(db, slug=slug, password=password, reset=reset)
    if not result.created:
        logger.info("demo company '%s' already exists; pass --reset to rebuild it", slug)
        return
    logger.info(
        "demo company '%s' ready: %d applications, %d completed quizzes. "
        "Log in as erika@%s.example / %s (careers page at /c/%s)",
        slug,
        result.applications,
        result.attempts,
        slug,
        password,
        slug,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed the ACME Ganek demo workspace.")
    parser.add_argument("--slug", default=os.environ.get("GANEK_DEMO_SLUG") or DEFAULT_SLUG)
    parser.add_argument("--reset", action="store_true", help="delete and rebuild if it exists")
    args = parser.parse_args()
    password = settings.demo_password or DEFAULT_PASSWORD
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    asyncio.run(run(slug=args.slug, password=password, reset=args.reset))


if __name__ == "__main__":
    main()
