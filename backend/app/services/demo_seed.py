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
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from textwrap import dedent
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
    EmploymentType,
    Job,
    JobView,
    Questionnaire,
    QuizAttempt,
    RemotePolicy,
    SalaryPeriod,
    Scorecard,
    User,
    UserRole,
)
from app.models.scorecard import Recommendation
from app.schemas.jobs import JobCreate, QuizConfigSchema
from app.schemas.public import ApplicationSubmit
from app.schemas.scorecard_template import ScorecardCriterion, ensure_criterion_ids
from app.services import activity, email_render, screening, storage
from app.services import applications as applications_service
from app.services import company as company_service
from app.services import jobs as jobs_service
from app.services import quiz as quiz_service
from app.services.email_templates import PREVIEW_LINK_PLACEHOLDER
from app.services.screening import ScreeningAnswerIn, ScreeningQuestion

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
    salary_period: SalaryPeriod = SalaryPeriod.YEAR
    remote_policy: RemotePolicy = RemotePolicy.ONSITE
    employment_type: EmploymentType = EmploymentType.FULL_TIME
    closes_in_days: int | None = None  # advisory deadline, relative so the reset keeps it
    # job-specific screening questions, asked after the company default set
    screening: tuple[ScreeningQuestion, ...] = ()
    # attach DEMO_QUESTIONNAIRE instead of tag-auto selection
    questionnaire: bool = False


def _md(text: str) -> str:
    return dedent(text).strip() + "\n"


ABOUT = (
    "ACME Ganek builds autonomous warehouse robots and the software that runs them. "
    "We are 60 people in Berlin, hardware and software under one roof, and about "
    "2,000 robots in customer warehouses that phone home every few seconds."
)

# Screening questions (board card "Per-job screening questions"): ids are
# fixed so the seed stays deterministic. The company default set is copied
# into every job; the per-job ones follow it.
COMPANY_SCREENING = (
    ScreeningQuestion(
        id="sq_ac0e0001",
        type="yes_no",
        prompt="Do you have the right to work in the EU without visa sponsorship?",
        preferred="yes",
        required=True,
    ),
)
NOTICE_PERIOD = ScreeningQuestion(
    id="sq_ac0e0002", type="short_text", prompt="What is your notice period?"
)

JOBS = (
    _Job(
        "Backend Engineer (Python)",
        "Berlin",
        ["python", "fastapi", "sql"],
        8,
        _md(
            f"""
            {ABOUT}

            You will own the services behind our fleet telemetry: FastAPI, PostgreSQL,
            a worker queue, and the data volumes a few thousand robots produce around
            the clock. The team is six engineers; you report to the head of fleet software.

            ## What you will do

            - Design and ship the APIs the operator console and the robots talk to
            - Keep the telemetry pipeline fast as the fleet grows (about 40k events a minute today)
            - Own a few Postgres schemas end to end: migrations, indexes, query plans
            - Take part in a light on-call rotation, about one week in eight
            - Review code, write things down, and help two junior engineers grow

            ## What you bring

            - Solid Python and SQL; you have read an `EXPLAIN` output and acted on it
            - You have run a service in production and been paged for it
            - You can explain a trade-off in writing, to people outside your team
            - Working proficiency in English; German is a plus, not a must

            ## Nice to have

            - FastAPI, SQLAlchemy or a comparable async stack
            - Time-series data, message queues, or anything that moves hardware

            ## What we offer

            - 65,000 to 85,000 EUR a year, depending on experience
            - Hybrid: two days a week in our Berlin-Adlershof lab, the rest wherever you work best
            - 30 days of vacation, a 1,500 EUR yearly learning budget, Deutschlandticket
            - A robot with your name on it. Really.
            """
        ),
        (65_000, 85_000),
        remote_policy=RemotePolicy.HYBRID,
        screening=(
            ScreeningQuestion(
                id="sq_ac0e0101",
                type="single_choice",
                prompt="How many years have you run a Python service in production?",
                options=["None yet", "1 to 2", "3 to 5", "More than 5"],
            ),
            NOTICE_PERIOD,
        ),
    ),
    _Job(
        "Site Reliability Engineer",
        "Berlin",
        ["devops", "sql"],
        6,
        _md(
            f"""
            {ABOUT}

            Keep the control plane boring. You will own observability, capacity and the
            on-call setup for the platform the robots report to: Kubernetes on bare metal
            in two data centres, Postgres, a lot of Grafana.

            ## What you will do

            - Run and improve the Kubernetes clusters that host the fleet platform
            - Define SLOs with the product teams and make the dashboards that show them
            - Make deploys safer: progressive rollout, automatic rollback, fewer surprises
            - Lead incident reviews that end with a fix, not with blame
            - Be in the on-call rotation (paid, about one week in six)

            ## What you bring

            - Three or more years running production infrastructure
            - Comfortable with Linux, networking and at least one infra-as-code tool
            - Enough SQL to find the slow query yourself
            - Calm in an incident and curious afterwards

            ## Nice to have

            - Bare-metal Kubernetes, Postgres operations, or fleet-scale MQTT

            ## What we offer

            - 70,000 to 90,000 EUR a year, plus on-call pay
            - Hybrid from Berlin; remote weeks are fine when nothing is on fire
            - 30 days of vacation, learning budget, a real hardware lab next door
            """
        ),
        (70_000, 90_000),
        remote_policy=RemotePolicy.HYBRID,
        questionnaire=True,
        screening=(
            ScreeningQuestion(
                id="sq_ac0e0201",
                type="acknowledgment",
                prompt=(
                    "This role is part of a paid on-call rotation, about one week in six. "
                    "I am fine with that."
                ),
            ),
        ),
    ),
    _Job(
        "Product Designer",
        "Berlin",
        ["design", "figma"],
        None,
        _md(
            f"""
            {ABOUT}

            You will design the operator console our customers run their warehouses from:
            a live map of a few hundred robots, task queues, alerts. The people using it
            work night shifts on the warehouse floor. Their feedback is honest and fast.

            ## What you will do

            - Own the console end to end: research, flows, visual design, handoff
            - Spend time in customer warehouses and bring back what you saw
            - Grow a small design system that engineers like using
            - Pair with frontend engineers daily; you ship together

            ## What you bring

            - A portfolio of shipped product work, ideally for complex or operational tools
            - Fluent in Figma and in talking to engineers about what is feasible
            - You test with real users and change your mind when the data says so
            - Comfortable being the only designer, for now

            ## Nice to have

            - Data visualisation, maps, or anything real-time

            ## What we offer

            - Competitive salary, shared once we know your level
            - On-site in Berlin-Adlershof: the robots are here, and so are the users
            - 30 days of vacation, conference budget, a quiet studio corner
            """
        ),
        None,
        screening=(
            ScreeningQuestion(
                id="sq_ac0e0301",
                type="short_text",
                prompt="Link one piece of work you are proud of and tell us why, in a line.",
                required=True,
            ),
        ),
    ),
    _Job(
        "Senior Frontend Engineer",
        "Anywhere in the EU",
        ["react", "typescript", "javascript"],
        None,
        _md(
            f"""
            {ABOUT}

            React and TypeScript on a real-time fleet map that renders a few hundred moving
            robots at 60 fps in a browser on a warehouse laptop. You care about rendering
            performance and accessibility in equal measure, and you have opinions about both.

            ## What you will do

            - Lead frontend architecture for the operator console (Next.js, React, WebSockets)
            - Make the map fast on hardware that is not fast
            - Build the design system together with our product designer
            - Mentor two mid-level engineers and set the bar in code review

            ## What you bring

            - Five or more years of production frontend work, TypeScript for most of it
            - You have profiled a React app and fixed what you found
            - Accessibility is part of done for you, not a ticket for later
            - You write clear RFCs and are happy working async across time zones

            ## Nice to have

            - Canvas or WebGL rendering, maps, or real-time data

            ## What we offer

            - 75,000 to 95,000 EUR a year
            - Fully remote within the EU, with two team weeks in Berlin a year
            - 30 days of vacation, home office budget, learning budget
            """
        ),
        (75_000, 95_000),
        remote_policy=RemotePolicy.REMOTE,
        screening=(
            ScreeningQuestion(
                id="sq_ac0e0401",
                type="yes_no",
                prompt="Can you overlap at least four hours a day with Berlin working hours?",
                preferred="yes",
                required=True,
            ),
        ),
    ),
    _Job(
        "Robotics Platform Engineer (Go)",
        "Berlin",
        ["go", "devops"],
        6,
        _md(
            f"""
            {ABOUT}

            You will work on the software that runs on the robot: a Go agent that talks to
            the motor controllers, keeps the local task queue, and syncs with the fleet
            platform over flaky warehouse Wi-Fi. When it misbehaves, a 400 kg machine stops.

            ## What you will do

            - Build and maintain the on-robot agent in Go, from the serial port up
            - Design the sync protocol between robots and the fleet platform
            - Make over-the-air updates boring: staged rollouts, rollback, health checks
            - Spend time in the lab with the hardware team when a robot does something odd

            ## What you bring

            - Strong Go, with care for concurrency, memory and failure modes
            - Experience with systems that talk to hardware or run at the edge
            - You can read a packet capture and a motor datasheet
            - You like fixing the root cause more than the symptom

            ## Nice to have

            - ROS 2, CAN bus, MQTT, or embedded Linux

            ## What we offer

            - 70,000 to 92,000 EUR a year
            - On-site in Berlin-Adlershof, in the building with the test warehouse
            - 30 days of vacation, learning budget, Deutschlandticket
            """
        ),
        (70_000, 92_000),
        screening=(
            ScreeningQuestion(
                id="sq_ac0e0501",
                type="single_choice",
                prompt="Have you worked on software that moves physical hardware?",
                options=["No", "A hobby project", "Yes, at work"],
            ),
            NOTICE_PERIOD,
        ),
    ),
    _Job(
        "Working Student, Data Engineering",
        "Berlin",
        ["sql", "python"],
        5,
        _md(
            f"""
            {ABOUT}

            Help the fleet-data team turn robot telemetry into answers. You will write SQL
            and Python, build small pipelines, and present what you found to the people who
            run the warehouses. 15 to 20 hours a week, around your lectures.

            ## What you will do

            - Build and maintain reports on fleet health, task throughput and battery life
            - Write the odd Python job that cleans, loads or checks data
            - Help us document the data model so new colleagues find their way

            ## What you bring

            - Enrolled at a university in Germany for the next 12 months
            - SQL you are comfortable with, Python you want to get better at
            - Curiosity, and the patience to ask why a number looks wrong

            ## What we offer

            - 16 to 18 EUR an hour, flexible around exam periods
            - Hybrid: one day a week in the Berlin lab, the rest from wherever you study
            - A mentor on the team and a real chance to join full time afterwards
            """
        ),
        (16, 18),
        salary_period=SalaryPeriod.HOUR,
        remote_policy=RemotePolicy.HYBRID,
        employment_type=EmploymentType.PART_TIME,
        screening=(
            ScreeningQuestion(
                id="sq_ac0e0601",
                type="yes_no",
                prompt="Will you be enrolled at a university in Germany for the next 12 months?",
                preferred="yes",
                required=True,
            ),
            ScreeningQuestion(
                id="sq_ac0e0602",
                type="single_choice",
                prompt="How many hours a week can you work during the semester?",
                options=["10", "15", "20"],
            ),
        ),
    ),
    _Job(
        "Engineering Manager, Fleet Software",
        "Berlin",
        ["leadership"],
        None,
        _md(
            f"""
            {ABOUT}

            Lead the fleet software group: three teams, 14 engineers, the platform every
            robot reports to. You will still read code, but your job is the people, the
            roadmap and the way the group works with hardware, product and customers.

            ## What you will do

            - Manage three team leads and grow the next ones
            - Own the fleet software roadmap together with product
            - Run hiring for the group, from the job post to the offer
            - Keep delivery predictable and the on-call load humane

            ## What you bring

            - Three or more years managing software teams, ideally more than one at a time
            - A technical background in backend or distributed systems
            - You have hired, coached and, when needed, let people go, with care
            - Clear in writing, direct and kind in person

            ## What we offer

            - 95,000 to 120,000 EUR a year, plus a yearly bonus
            - Hybrid from Berlin, three days a week on site
            - 30 days of vacation, a leadership coach, a seat at the company table

            Applications close in three weeks. We review them as they come in.
            """
        ),
        (95_000, 120_000),
        remote_policy=RemotePolicy.HYBRID,
        closes_in_days=21,
        screening=(
            ScreeningQuestion(
                id="sq_ac0e0701",
                type="single_choice",
                prompt="How many engineers have you managed directly?",
                options=["None", "1 to 3", "4 to 8", "More than 8"],
            ),
        ),
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
    # the funnel stage a rejected or withdrawn candidate left from (None = straight from new)
    left_from: ApplicationStage | None = None
    # age of the application in days; None = spread by list position. Pins the stalled role.
    days_ago: float | None = None
    # screening answers by question position (company default first); a
    # position not listed gets a fitting default (_answers_for)
    answers: dict[int, str | bool | None] = field(default_factory=dict)


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
    _Candidate("Diego Alvarez", 0, 5, ApplicationStage.HIRED, source="link:newsletter"),
    _Candidate("Nina Lindqvist", 0, 5, ApplicationStage.NEW, source="google"),
    _Candidate("Pavel Horak", 0, 4, ApplicationStage.OFFER, source="linkedin"),
    _Candidate("Sofia Ricci", 0, 4, ApplicationStage.NEW, source="ref:robotics-weekly.example"),
    _Candidate(
        "Lucas Moreau", 0, 3, ApplicationStage.REJECTED, left_from=ApplicationStage.SCREENING
    ),  # direct
    _Candidate("Aisha Khan", 0, 3, ApplicationStage.NEW, flag="fast", source="linkedin"),
    _Candidate(
        "Tomas Ferreira", 0, 2, ApplicationStage.REJECTED, source="google", answers={0: "no"}
    ),
    _Candidate("Ingrid Solberg", 0, None, ApplicationStage.NEW, source="link:newsletter"),  # open
    _Candidate("Marek Novak", 0, None, ApplicationStage.NEW, source="hn"),
    _Candidate(
        "Yuki Tanaka", 0, None, ApplicationStage.REJECTED, left_from=ApplicationStage.INTERVIEW
    ),  # direct
    # the Senior Frontend role is the stalled one: nothing has moved for 8+ days
    _Candidate("Lena Fischer", 3, None, ApplicationStage.SCREENING, source="linkedin", days_ago=16),
    _Candidate(
        "Omar Haddad", 3, None, ApplicationStage.NEW, days_ago=12, answers={1: "no"}
    ),  # direct
    _Candidate("Chloe Martin", 1, None, ApplicationStage.NEW, source="indeed"),
    # two older hires: with Diego they give the reports a median time to hire
    _Candidate("Ravi Mehta", 1, 5, ApplicationStage.HIRED, source="linkedin", days_ago=19),
    _Candidate("Clara Vogel", 2, None, ApplicationStage.HIRED, source="website", days_ago=15),
    # the Go role is young and busy: four applicants in a week, one already interviewing
    _Candidate(
        "Priya Raman",
        4,
        5,
        ApplicationStage.INTERVIEW,
        github="https://github.com/Ganek-dev",
        message="I wrote the OTA updater for a fleet of delivery robots. Happy to talk CAN bus.",
        source="github",
        days_ago=6,
        answers={1: "Yes, at work"},
    ),
    _Candidate("Jonas Weber", 4, 4, ApplicationStage.SCREENING, source="linkedin", days_ago=5),
    _Candidate("Elif Demir", 4, 3, ApplicationStage.NEW, source="hn", days_ago=2.5),
    _Candidate(
        "Ben Carter", 4, 2, ApplicationStage.NEW, source="google", days_ago=1.2, answers={1: "No"}
    ),
    # working student: one quiz done, one still open
    _Candidate("Leon Schulz", 5, 4, ApplicationStage.NEW, source="link:uni-jobboard", days_ago=4),
    _Candidate(
        "Amara Osei", 5, None, ApplicationStage.NEW, source="link:uni-jobboard", days_ago=0.8
    ),
    # the manager role went live this week
    _Candidate(
        "Felix Brandner",
        6,
        None,
        ApplicationStage.NEW,
        linkedin="https://www.linkedin.com/company/ganek-io",
        source="xing",
        days_ago=3,
        answers={1: "4 to 8"},
    ),
)

# Page views per job and day (spec job posts v2 5.5), by source, for the last
# 30 days: base loads per weekday, a share per source, and one newsletter
# send ten days ago that shows as a spike. Shares sum to 1.
VIEW_BASE_PER_JOB = (28, 14, 10, 18, 16, 9, 12)  # index into JOBS
VIEW_SHARES = (
    ("direct", 0.30),
    ("linkedin", 0.25),
    ("google", 0.18),
    ("indeed", 0.08),
    ("link:newsletter", 0.06),
    ("website", 0.03),
    ("hn", 0.03),
    ("ref:robotics-weekly.example", 0.02),
    ("link:uni-jobboard", 0.01),
    ("xing", 0.01),
    ("github", 0.01),
)
NEWSLETTER_DAYS_AGO = 10
VIEW_DAYS = 30

# the default scorecard template every seeded job copies (spec scorecards 6)
SCORECARD_CRITERIA = ("Problem solving", "Communication", "Role knowledge")

# One curated set, so the questionnaires page and the job form show the
# feature instead of an empty state. Open-bank ids, in serve order; the
# SRE job uses it, every other quiz stays tag-auto.
DEMO_QUESTIONNAIRE = {
    "name": "SRE on-call basics",
    "description": (
        "Six questions for the SRE role: health checks, observability, safe "
        "rollouts, what Kubernetes does, secrets, and reading a query plan."
    ),
    "question_refs": [
        "devops-healthcheck-1",
        "devops-observability-1",
        "devops-blue-green-1",
        "devops-orchestrator-1",
        "devops-secrets-1",
        "sql-explain-1",
    ],
}

# index into CANDIDATES: Mia (interview) holds the submitted scorecard, Hanna
# (screening, quiz and CV) Max's open request, Karol (interview) Erika's task
SCORECARD_DONE, SCORECARD_WAITING, SCORECARD_MINE = 0, 3, 2

NOTES = (
    (0, "erika", "Strong on the pipeline questions. Pair her with Jonas for the systems round."),
    (2, "jonas", "Asked good questions about on-call. Check notice period before the offer talk."),
)


def _email(name: str) -> str:
    return name.lower().replace(" ", ".") + "@example.com"


NOTICE_PERIODS = ("Available now", "4 weeks", "3 months to the end of a quarter", "6 weeks")


def _answers_for(
    spec: _Candidate, questions: list[ScreeningQuestion], rng: random.Random
) -> list[dict[str, Any]]:
    """The candidate's screening answers in the shape the apply route stores:
    overrides from the spec by position, a fitting default for the rest (the
    preferred answer where there is one, a random option, a notice period).
    build_answers validates like the route does, so a bad override fails loudly."""
    answers: list[ScreeningAnswerIn] = []
    for position, question in enumerate(questions):
        answer: str | bool | None
        if position in spec.answers:
            answer = spec.answers[position]
        elif question.type == "acknowledgment":
            answer = True
        elif question.type == "yes_no":
            answer = question.preferred or "yes"
        elif question.type == "single_choice":
            answer = rng.choice(question.options or [])
        elif question.required:
            answer = "A fleet dashboard I shipped last year. People open it every shift."
        else:
            answer = rng.choice(NOTICE_PERIODS)
        answers.append(ScreeningAnswerIn(question_id=question.id, answer=answer))
    return screening.build_answers(questions, answers)


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


REJECTED, WITHDRAWN = ApplicationStage.REJECTED, ApplicationStage.WITHDRAWN
FUNNEL = (
    ApplicationStage.NEW,
    ApplicationStage.SCREENING,
    ApplicationStage.INTERVIEW,
    ApplicationStage.OFFER,
    ApplicationStage.HIRED,
)


async def _walk_stages(
    db: AsyncSession,
    application: Application,
    target: ApplicationStage,
    actor_id: uuid.UUID,
    left_from: ApplicationStage | None = None,
) -> Application:
    """Move through every funnel stage up to ``target`` with set_stage, so a
    stage.changed row exists per step. A rejected or withdrawn target walks to
    ``left_from`` first. set_stage queues no mail (the routers do), so
    walking sends nothing; the sent mail the demo shows is written by hand."""
    goal = left_from or ApplicationStage.NEW if target in (REJECTED, WITHDRAWN) else target
    for stage in FUNNEL[1 : FUNNEL.index(goal) + 1]:
        application = await applications_service.set_stage(
            db, application, stage, actor_user_id=actor_id
        )
    if target in (REJECTED, WITHDRAWN):
        application = await applications_service.set_stage(
            db, application, target, actor_user_id=actor_id
        )
    return application


async def _spread_history(
    db: AsyncSession, application: Application, step: timedelta = timedelta(days=2)
) -> None:
    """Space the stage.changed rows out: the i-th (from 1) lands i steps after
    the application was created, and the stage stamp follows the last one.
    The step shrinks for a young application so no row sits in the future."""
    events = (
        (
            await db.execute(
                select(ActivityLog)
                .where(
                    ActivityLog.application_id == application.id,
                    ActivityLog.type == activity.STAGE_CHANGED,
                )
                .order_by(ActivityLog.created_at, ActivityLog.id)
            )
        )
        .scalars()
        .all()
    )
    if not events:
        return
    room = datetime.now(UTC) - application.created_at - timedelta(hours=2)
    step = max(min(step, room / len(events)), timedelta(minutes=1))
    for position, event in enumerate(events, start=1):
        event.created_at = application.created_at + position * step
    application.stage_changed_at = events[-1].created_at
    if application.decided_at is not None:
        application.decided_at = events[-1].created_at
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
        description="Robots that move the boxes. Software that moves the robots.",
        website=f"https://{domain}",
        socials={
            "github": "https://github.com/Ganek-dev",
            "linkedin": "https://www.linkedin.com/company/ganek-io",
        },
        theme={"primary_color": BRAND_PRIMARY},
        settings={
            "legal_name": "ACME Ganek GmbH",
            "contact_email": f"privacy@{domain}",
            "quiz_expired_reissue": "auto",
        },
        screening_questions=[question.model_dump() for question in COMPANY_SCREENING],
        scorecard_template=ensure_criterion_ids(
            [ScorecardCriterion(label=label) for label in SCORECARD_CRITERIA]
        ),
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
    # a reviewer seat: sees only the candidates he holds a scorecard on
    max_berger = User(
        company_id=company.id,
        email=f"max@{domain}",
        password_hash=hash_password(password),
        role=UserRole.REVIEWER,
        is_active=True,
        display_name="Max Berger",
    )
    db.add_all([erika, jonas, max_berger])
    await db.commit()
    authors = {"erika": erika, "jonas": jonas}
    questionnaire = Questionnaire(company_id=company.id, **DEMO_QUESTIONNAIRE)
    db.add(questionnaire)
    await db.commit()

    jobs: list[Job] = []
    now = datetime.now(UTC)
    for spec in JOBS:
        job = await jobs_service.create_job(
            db,
            company,
            JobCreate(
                title=spec.title,
                description_md=spec.description_md,
                location=spec.location,
                remote_policy=spec.remote_policy,
                employment_type=spec.employment_type,
                tags=spec.tags,
                salary_min=spec.salary[0] if spec.salary else None,
                salary_max=spec.salary[1] if spec.salary else None,
                salary_currency="EUR" if spec.salary else None,
                salary_period=spec.salary_period,
                closes_at=(
                    now + timedelta(days=spec.closes_in_days)
                    if spec.closes_in_days is not None
                    else None
                ),
                screening_questions=[*COMPANY_SCREENING, *spec.screening],
                quiz_config=QuizConfigSchema(
                    enabled=spec.quiz_questions is not None,
                    question_count=spec.quiz_questions or 6,
                    time_limit_seconds=20,
                    questionnaire_id=questionnaire.id if spec.questionnaire else None,
                ),
            ),
        )
        jobs.append(await jobs_service.publish_job(db, job))

    applications: list[Application] = []
    attempts = 0
    # the implicit spread covers the candidates without a pinned age: oldest
    # first, the newest a day ago, independent of how many pinned ones sit between
    unpinned = [i for i, cand in enumerate(CANDIDATES) if cand.days_ago is None]
    for index, cand in enumerate(CANDIDATES):
        job = jobs[cand.job]
        questions = [ScreeningQuestion(**q) for q in job.screening_questions]
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
            screening_answers=_answers_for(cand, questions, rng),
        )
        attempt = await _take_quiz(db, company, application, job, cand, rng)
        if attempt is not None and cand.correct is not None:
            attempts += 1
        if cand.stage is not ApplicationStage.NEW:
            application = await _walk_stages(db, application, cand.stage, erika.id, cand.left_from)
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
        # oldest applicants first in the list, the newest about a day ago
        if cand.days_ago is not None:
            days_ago = cand.days_ago
        else:
            position = unpinned.index(index)
            days_ago = 20.0 - position * (19.0 / max(1, len(unpinned) - 1))
            days_ago += rng.uniform(-0.3, 0.3)
        await _backdate(db, application, timedelta(days=max(0.1, days_ago)))
        await _spread_history(db, application)
        await _seed_sent_mail(db, company, application, job, cand.stage)

    # publish_job stamps "now"; a job cannot predate nobody applying to it,
    # so the board would read "1 d open" beside candidates 17 days old. Put
    # each job a day before its oldest applicant (relative, so the nightly
    # reset stays consistent).
    oldest = min(a.created_at for a in applications)
    for job in jobs:
        job.published_at = min(
            (a.created_at for a in applications if a.job_id == job.id), default=oldest
        ) - timedelta(days=1)
    await db.commit()

    await _seed_scorecards(db, applications, erika, jonas, max_berger)
    views = await _seed_views(db, jobs, rng)
    return SeedResult(
        created=True,
        company_id=company.id,
        applications=len(applications),
        attempts=attempts,
        views=views,
    )


async def _seed_scorecards(
    db: AsyncSession,
    applications: list[Application],
    erika: User,
    jonas: User,
    max_berger: User,
) -> None:
    """Three rows, dates relative to now so the nightly reset keeps them
    fresh: Max's submitted Yes, Max's request four days old (the queue reads
    "Waiting on Max Berger"), and one for Erika from Jonas. Rows are written
    directly, like the seeded mail: a demo instance never sends any.
    The old request carries ``reminded_at`` so remind_scorecards never
    queues a mail to the fictional address."""
    now = datetime.now(UTC)
    plan = (
        # application, reviewer, requester, requested, due_from, submitted
        (SCORECARD_DONE, max_berger, erika, now - timedelta(days=6), now - timedelta(days=5)),
        (SCORECARD_WAITING, max_berger, erika, now - timedelta(days=4), None),
        (SCORECARD_MINE, erika, jonas, now - timedelta(hours=3), None),
    )
    for index, reviewer, requester, due_from, submitted_at in plan:
        application = applications[index]
        job = await db.get(Job, application.job_id)
        assert job is not None
        snapshot = [dict(c) for c in job.scorecard_template]
        row = Scorecard(
            company_id=application.company_id,
            application_id=application.id,
            job_id=job.id,
            reviewer_user_id=reviewer.id,
            requested_by_user_id=requester.id,
            requested_at=due_from,
            due_from=due_from,
            criteria_snapshot=snapshot,
            created_at=due_from,
            updated_at=due_from,
        )
        if reviewer is max_berger and submitted_at is None:
            row.reminded_at = now - timedelta(days=1)
        if submitted_at is not None:
            row.ratings = {
                str(c["id"]): rating for c, rating in zip(snapshot, (4, 3, 3), strict=True)
            }
            row.recommendation = Recommendation.YES
            row.comment = "Clear thinker, explains trade-offs well. Happy to see this one go on."
            row.submitted_at = submitted_at
            row.updated_at = submitted_at
        db.add(row)
        await db.flush()
        label = reviewer.display_label
        events = [(activity.SCORECARD_REQUESTED, requester, due_from)]
        if submitted_at is not None:
            events.append((activity.SCORECARD_SUBMITTED, reviewer, submitted_at))
        for kind, actor, at in events:
            db.add(
                ActivityLog(
                    company_id=application.company_id,
                    actor_user_id=actor.id,
                    application_id=application.id,
                    type=kind,
                    payload={"scorecard_id": str(row.id), "reviewer_label": label},
                    created_at=at,
                )
            )
    await db.commit()


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
