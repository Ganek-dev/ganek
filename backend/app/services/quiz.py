"""Quiz attempt engine. Every rule from ANTI_CHEAT.md that matters lives here.

Non-negotiables implemented server-side:
- question selection is frozen at attempt creation (stratified over tags)
- questions are served one at a time; the full set is never exposed
- deadlines are set at serve time; late or missing answers score zero
- options are shuffled per serve; scoring only ever happens here
"""

import random
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core import queue
from app.core.config import settings
from app.models import (
    MAX_DIFFICULTY,
    MIN_DIFFICULTY,
    Application,
    AttemptAnswer,
    AttemptStatus,
    Company,
    Job,
    Question,
    Questionnaire,
    QuestionStatus,
    QuizAttempt,
)
from app.services import activity

# Selection/shuffle order is an anti-cheat surface: use a CSPRNG by default.
_default_rng: random.Random = random.SystemRandom()


class QuizError(Exception):
    pass


class AttemptExpiredError(QuizError):
    """The attempt was not started within its TTL."""


class NoOpenQuestionError(QuizError):
    """An answer arrived for a question that is not currently open."""


DEFAULT_TIME_LIMIT_SECONDS = 20


@dataclass(frozen=True)
class QuizConfig:
    enabled: bool = False
    tags: list[str] = field(default_factory=list)
    question_count: int = 6
    include_company_questions: bool = True
    time_limit_seconds: int | None = DEFAULT_TIME_LIMIT_SECONDS
    difficulties: list[int] = field(default_factory=list)  # 1-5; empty = all
    exclude_ids: list[str] = field(default_factory=list)
    # When set, the referenced Questionnaire's ordered question_refs replace
    # tag-auto selection — tags and question_count no longer influence pool
    # composition (they may still be edited but are ignored on attempt).
    questionnaire_id: uuid.UUID | None = None


# configs written before the 5-level migration stored named bands
_LEGACY_DIFFICULTIES = {"easy": (1, 2), "medium": (3,), "hard": (4, 5)}


def _parse_difficulties(raw: Any) -> list[int]:
    if not isinstance(raw, list):
        return []
    levels: set[int] = set()
    for value in raw:
        if isinstance(value, str) and value in _LEGACY_DIFFICULTIES:
            levels.update(_LEGACY_DIFFICULTIES[value])
        elif (
            isinstance(value, int)
            and not isinstance(value, bool)
            and MIN_DIFFICULTY <= value <= MAX_DIFFICULTY
        ):
            levels.add(value)
    return sorted(levels)


def parse_quiz_config(job: Job) -> QuizConfig:
    raw = job.quiz_config or {}
    tags = raw.get("tags") or job.tags
    raw_limit = raw.get("time_limit_seconds", DEFAULT_TIME_LIMIT_SECONDS)
    raw_questionnaire = raw.get("questionnaire_id")
    questionnaire_id: uuid.UUID | None
    if raw_questionnaire in (None, ""):
        questionnaire_id = None
    elif isinstance(raw_questionnaire, uuid.UUID):
        questionnaire_id = raw_questionnaire
    else:
        try:
            questionnaire_id = uuid.UUID(str(raw_questionnaire))
        except ValueError:
            questionnaire_id = None
    return QuizConfig(
        enabled=bool(raw.get("enabled", False)),
        tags=list(tags),
        question_count=int(raw.get("question_count", 6)),
        include_company_questions=bool(raw.get("include_company_questions", True)),
        time_limit_seconds=int(raw_limit) if raw_limit is not None else None,
        difficulties=_parse_difficulties(raw.get("difficulties")),
        exclude_ids=[str(qid) for qid in raw.get("exclude_ids") or []],
        questionnaire_id=questionnaire_id,
    )


def _now() -> datetime:
    return datetime.now(UTC)


async def _question_pool(
    db: AsyncSession,
    company: Company,
    config: QuizConfig,
    *,
    apply_exclusions: bool = True,
) -> list[Question]:
    """Eligible questions for a job's quiz.

    ``apply_exclusions=False`` returns the pool ignoring per-job excludes and
    the company blocklist — the preview endpoint uses it so recruiters can see
    (and un-exclude) what they filtered out.
    """
    query = select(Question).where(
        Question.status == QuestionStatus.ACTIVE,
        Question.tags.overlap(config.tags),
    )
    if config.include_company_questions:
        query = query.where((Question.company_id.is_(None)) | (Question.company_id == company.id))
    else:
        query = query.where(Question.company_id.is_(None))
    if config.difficulties:
        query = query.where(Question.difficulty.in_(config.difficulties))
    if apply_exclusions:
        excluded = set(config.exclude_ids) | set(company.blocked_question_ids or [])
        if excluded:
            query = query.where(Question.id.not_in(excluded))
    return list((await db.execute(query)).scalars().all())


async def get_questionnaire_for_company(
    db: AsyncSession, company: Company, questionnaire_id: uuid.UUID
) -> Questionnaire | None:
    return (
        await db.execute(
            select(Questionnaire).where(
                Questionnaire.company_id == company.id,
                Questionnaire.id == questionnaire_id,
            )
        )
    ).scalar_one_or_none()


async def _resolve_questionnaire_pool(
    db: AsyncSession,
    company: Company,
    questionnaire: Questionnaire,
) -> list[Question]:
    """Load active + tenant-visible Question rows for a questionnaire's refs,
    preserving the curated order. Missing/retired refs are silently skipped —
    the recruiter sees the difference in the preview endpoint."""
    if not questionnaire.question_refs:
        return []
    rows = (
        (
            await db.execute(
                select(Question).where(
                    Question.id.in_(questionnaire.question_refs),
                    Question.status == QuestionStatus.ACTIVE,
                    (Question.company_id.is_(None)) | (Question.company_id == company.id),
                )
            )
        )
        .scalars()
        .all()
    )
    by_id = {q.id: q for q in rows}
    return [by_id[ref] for ref in questionnaire.question_refs if ref in by_id]


def stratified_sample(
    pool: list[Question], tags: list[str], count: int, rng: random.Random
) -> list[str]:
    """Round-robin over tags so every requested tag is represented when possible."""
    by_tag: dict[str, list[Question]] = {tag: [q for q in pool if tag in q.tags] for tag in tags}
    chosen: list[str] = []
    chosen_set: set[str] = set()
    tag_cycle = [tag for tag in tags if by_tag[tag]]
    rng.shuffle(tag_cycle)
    while len(chosen) < count and tag_cycle:
        for tag in list(tag_cycle):
            candidates = [q for q in by_tag[tag] if q.id not in chosen_set]
            if not candidates:
                tag_cycle.remove(tag)
                continue
            picked = rng.choice(candidates)
            chosen.append(picked.id)
            chosen_set.add(picked.id)
            if len(chosen) >= count:
                break
    return chosen


async def create_attempt(
    db: AsyncSession,
    company: Company,
    application: Application,
    job: Job,
    *,
    rng: random.Random | None = None,
) -> QuizAttempt | None:
    """Create the (single) attempt for an application. None if quiz disabled/empty."""
    config = parse_quiz_config(job)
    if not config.enabled:
        return None
    picker = rng or _default_rng
    if config.questionnaire_id is not None:
        questionnaire = await get_questionnaire_for_company(db, company, config.questionnaire_id)
        if questionnaire is None:
            return None
        pool = await _resolve_questionnaire_pool(db, company, questionnaire)
        excluded = set(config.exclude_ids) | set(company.blocked_question_ids or [])
        eligible = [q for q in pool if q.id not in excluded]
        question_ids = [q.id for q in eligible]
        if questionnaire.shuffle:
            picker.shuffle(question_ids)
    else:
        if not config.tags:
            return None
        pool = await _question_pool(db, company, config)
        question_ids = stratified_sample(pool, config.tags, config.question_count, picker)
    if not question_ids:
        return None
    attempt = QuizAttempt(
        company_id=company.id,
        application_id=application.id,
        question_ids=question_ids,
        time_limit_seconds=config.time_limit_seconds,
        expires_at=_now() + timedelta(hours=settings.quiz_start_ttl_hours),
    )
    db.add(attempt)
    await db.commit()
    # auto-nudge (17b) shortly before the link dies; the job re-validates
    ttl = timedelta(hours=settings.quiz_start_ttl_hours)
    fire_at = attempt.expires_at - min(timedelta(days=3), ttl / 4)
    if fire_at > _now() + timedelta(hours=1):
        await queue.enqueue(
            "send_quiz_nudge",
            str(attempt.id),
            defer_until=fire_at,
            job_id=f"nudge-{attempt.id}",
        )
    return attempt


async def reissue_attempt(
    db: AsyncSession,
    company: Company,
    application: Application,
    job: Job,
    *,
    reason: str,
    mode: str,
    by_user_id: uuid.UUID | None,
    rng: random.Random | None = None,
) -> QuizAttempt | None:
    """Invalidate the current attempt and issue a fresh one (screen 24 / 27c).

    Fresh selection avoids every question served on prior attempts, topping
    up from the full pool only when it runs dry. Questionnaire-attached jobs
    re-serve the curated set (fresh order when shuffled) — the set IS the
    quiz. The superseded attempt keeps its data: completed/pending runs are
    marked invalidated, expired ones stay expired; either way the new row's
    ``integrity.reissue`` records where it came from, who did it, and why.
    None when the job's quiz is disabled or the pool is empty.
    """
    config = parse_quiz_config(job)
    if not config.enabled:
        return None
    prior = list(application.quiz_attempts)
    if not prior:
        return None
    picker = rng or _default_rng
    seen = {qid for attempt in prior for qid in attempt.question_ids}
    if config.questionnaire_id is not None:
        questionnaire = await get_questionnaire_for_company(db, company, config.questionnaire_id)
        if questionnaire is None:
            return None
        pool = await _resolve_questionnaire_pool(db, company, questionnaire)
        excluded = set(config.exclude_ids) | set(company.blocked_question_ids or [])
        question_ids = [q.id for q in pool if q.id not in excluded]
        if questionnaire.shuffle:
            picker.shuffle(question_ids)
    else:
        if not config.tags:
            return None
        pool = await _question_pool(db, company, config)
        fresh = [q for q in pool if q.id not in seen]
        question_ids = stratified_sample(fresh, config.tags, config.question_count, picker)
        if len(question_ids) < config.question_count:
            remaining = [q for q in pool if q.id not in set(question_ids)]
            question_ids += stratified_sample(
                remaining, config.tags, config.question_count - len(question_ids), picker
            )
    if not question_ids:
        return None

    latest = prior[-1]
    if latest.status is not AttemptStatus.EXPIRED:
        latest.status = AttemptStatus.INVALIDATED
    attempt = QuizAttempt(
        company_id=company.id,
        application_id=application.id,
        question_ids=question_ids,
        time_limit_seconds=config.time_limit_seconds,
        expires_at=_now() + timedelta(hours=settings.quiz_start_ttl_hours),
        integrity={
            "reissue": {
                "from_attempt_id": str(latest.id),
                "reason": reason,
                "mode": mode,
                "by_user_id": str(by_user_id) if by_user_id is not None else None,
                "at": _now().isoformat(),
            }
        },
    )
    db.add(attempt)
    activity.record(
        db,
        company_id=company.id,
        type=activity.QUIZ_REISSUED,
        actor_user_id=by_user_id,
        application_id=application.id,
        payload={"reason": reason, "mode": mode},
    )
    await db.commit()
    await db.refresh(attempt)
    return attempt


async def record_reissue_request(db: AsyncSession, attempt: QuizAttempt) -> QuizAttempt:
    """Candidate asked for a new link (27c, manual mode): surface it to the
    team on the expired attempt. Idempotent — repeats bump a count."""
    integrity = dict(attempt.integrity)
    request = dict(integrity.get("reissue_requested") or {})
    request["at"] = request.get("at") or _now().isoformat()
    request["count"] = int(request.get("count", 0)) + 1
    integrity["reissue_requested"] = request
    attempt.integrity = integrity
    await db.commit()
    await db.refresh(attempt)
    return attempt


async def dismiss_flags(
    db: AsyncSession, attempt: QuizAttempt, *, by_user_id: uuid.UUID
) -> QuizAttempt:
    """Screen 24 'looks fine': record the human review on the attempt."""
    integrity = dict(attempt.integrity)
    integrity["review"] = {
        "decision": "dismissed",
        "by_user_id": str(by_user_id),
        "at": _now().isoformat(),
    }
    attempt.integrity = integrity
    await db.commit()
    await db.refresh(attempt)
    return attempt


async def resolved_answers(db: AsyncSession, attempt: QuizAttempt) -> list[AttemptAnswer]:
    return list(
        (
            await db.execute(
                select(AttemptAnswer)
                .where(AttemptAnswer.attempt_id == attempt.id)
                .order_by(AttemptAnswer.served_at)
            )
        )
        .scalars()
        .all()
    )


MAX_EVENTS_PER_CALL = 100
MAX_STORED_EVENTS = 200
_COUNTED_EVENTS = {"blur", "paste", "resize"}


async def record_events(
    db: AsyncSession, attempt: QuizAttempt, events: list[dict[str, int | str | None]]
) -> None:
    """Record client integrity telemetry. Informational only — never scores.

    Each event may carry the question that was open when it happened, so
    recruiters can see exactly where in the quiz something occurred.
    """
    integrity = dict(attempt.integrity)
    stored: list[dict[str, int | str | None]] = list(integrity.get("events", []))
    for event in events[:MAX_EVENTS_PER_CALL]:
        kind = str(event.get("type", ""))
        if kind not in _COUNTED_EVENTS:
            continue
        key = f"{kind}_count"
        integrity[key] = min(int(integrity.get(key, 0)) + 1, 1000)
        duration: int | None = None
        if kind == "blur":
            duration = max(0, min(int(event.get("duration_ms", 0) or 0), 600_000))
            integrity["blur_total_ms"] = min(
                int(integrity.get("blur_total_ms", 0)) + duration, 36_000_000
            )
        question_id = event.get("question_id")
        if len(stored) < MAX_STORED_EVENTS:
            stored.append(
                {
                    "type": kind,
                    "question_id": str(question_id) if question_id else None,
                    "duration_ms": duration,
                }
            )
        else:
            integrity["events_truncated"] = True
    integrity["events"] = stored
    attempt.integrity = integrity
    await db.commit()


def _events_by_type(integrity: dict[str, Any], kind: str) -> list[dict[str, Any]]:
    return [e for e in integrity.get("events", []) if e.get("type") == kind]


def _question_positions(question_ids: list[str], attempt: QuizAttempt) -> str:
    positions = sorted(
        attempt.question_ids.index(qid) + 1 for qid in question_ids if qid in attempt.question_ids
    )
    return ", ".join(f"Q{p}" for p in positions)


def _integrity_flags(
    integrity: dict[str, Any], answers: list[AttemptAnswer], attempt: QuizAttempt
) -> list[dict[str, Any]]:
    """Structured flags: what was detected, why it was flagged, and where."""
    flags: list[dict[str, Any]] = []

    blur_events = _events_by_type(integrity, "blur")
    blur_count = int(integrity.get("blur_count", 0) or 0)
    if blur_count:
        seconds = round(int(integrity.get("blur_total_ms", 0) or 0) / 1000)
        question_ids = sorted({e["question_id"] for e in blur_events if e.get("question_id")})
        where = _question_positions(question_ids, attempt)
        flags.append(
            {
                "code": "tab_hidden",
                "summary": f"left the tab {blur_count}x (~{seconds}s)",
                "detail": (
                    f"The quiz tab was hidden {blur_count} time(s) for about {seconds}s "
                    "total while a question was open — consistent with switching to "
                    "another window (search, notes, chat). Can also be a notification "
                    "or an accidental switch; check which questions were affected."
                    + (f" Occurred during {where}." if where else "")
                ),
                "question_ids": question_ids,
            }
        )

    paste_events = _events_by_type(integrity, "paste")
    paste_count = int(integrity.get("paste_count", 0) or 0)
    if paste_count:
        question_ids = sorted({e["question_id"] for e in paste_events if e.get("question_id")})
        where = _question_positions(question_ids, attempt)
        flags.append(
            {
                "code": "paste",
                "summary": f"paste detected x{paste_count}",
                "detail": (
                    "Paste events fired inside the quiz. There is nothing to type in a "
                    "multiple-choice quiz, so pasting usually means external tooling "
                    "was in play." + (f" Occurred during {where}." if where else "")
                ),
                "question_ids": question_ids,
            }
        )

    timed = [
        (a, (a.answered_at - a.served_at).total_seconds())
        for a in answers
        if a.answered_at is not None and a.answer_key is not None
    ]
    if timed:
        avg = sum(seconds for _, seconds in timed) / len(timed)
        integrity["avg_answer_ms"] = int(avg * 1000)
        if avg < 3 and len(timed) == len(answers):
            fast_ids = [a.question_id for a, seconds in timed if seconds < 3]
            where = _question_positions(fast_ids, attempt)
            flags.append(
                {
                    "code": "very_fast",
                    "summary": f"answered very fast (avg {avg:.1f}s)",
                    "detail": (
                        f"Every question was answered, averaging {avg:.1f}s — near the "
                        "floor of reading time. Plausible for strong recall on easy "
                        "questions, but combined with a low score it suggests guessing; "
                        "combined with tab-switching it suggests a second screen."
                        + (f" Fastest answers: {where}." if where else "")
                    ),
                    "question_ids": fast_ids,
                }
            )
    return flags


async def _finalize(db: AsyncSession, attempt: QuizAttempt) -> None:
    answers = await resolved_answers(db, attempt)
    questions = {
        q.id: q
        for q in (
            await db.execute(select(Question).where(Question.id.in_(attempt.question_ids)))
        ).scalars()
    }
    total = len(answers)
    correct = sum(1 for a in answers if a.is_correct)
    per_tag: dict[str, dict[str, int]] = {}
    for answer in answers:
        for tag in questions[answer.question_id].tags:
            bucket = per_tag.setdefault(tag, {"correct": 0, "total": 0})
            bucket["total"] += 1
            if answer.is_correct:
                bucket["correct"] += 1
    attempt.score = correct / total if total else 0.0
    attempt.per_tag_scores = per_tag
    integrity = dict(attempt.integrity)
    integrity["flags"] = _integrity_flags(integrity, answers, attempt)
    attempt.integrity = integrity
    attempt.status = AttemptStatus.COMPLETED
    attempt.completed_at = _now()
    activity.record(
        db,
        company_id=attempt.company_id,
        type=activity.QUIZ_FINISHED,
        application_id=attempt.application_id,
        payload={"score": attempt.score},
    )
    await db.commit()


def effective_time_limit(attempt: QuizAttempt, question: Question) -> int:
    """Seconds the candidate gets: the attempt's frozen per-job limit, else the question's own."""
    return attempt.time_limit_seconds or question.time_limit_seconds


async def build_quiz_preview(
    db: AsyncSession,
    company: Company,
    job: Job,
    *,
    rng: random.Random | None = None,
) -> tuple[QuizConfig, list[Question], set[str], list[str]]:
    """What this job's quiz would look like right now.

    Returns (config, full pool WITHOUT exclusions applied, eligible ids after
    exclusions, sample question ids drawn like a real attempt). Preview only —
    never persisted; every call redraws the sample.
    """
    config = parse_quiz_config(job)
    blocked = set(company.blocked_question_ids or [])
    excluded_ids = set(config.exclude_ids) | blocked

    if config.questionnaire_id is not None:
        questionnaire = await get_questionnaire_for_company(db, company, config.questionnaire_id)
        if questionnaire is None:
            return config, [], set(), []
        pool = await _resolve_questionnaire_pool(db, company, questionnaire)
        eligible = [q for q in pool if q.id not in excluded_ids]
        sample = [q.id for q in eligible]
        if questionnaire.shuffle:
            (rng or _default_rng).shuffle(sample)
        return config, pool, {q.id for q in eligible}, sample

    if not config.tags:
        return config, [], set(), []
    pool = await _question_pool(db, company, config, apply_exclusions=False)
    eligible = [q for q in pool if q.id not in excluded_ids]
    eligible_ids = {q.id for q in eligible}
    sample = stratified_sample(eligible, config.tags, config.question_count, rng or _default_rng)
    return config, pool, eligible_ids, sample


async def current_or_next_question(
    db: AsyncSession, attempt: QuizAttempt, *, rng: random.Random | None = None
) -> tuple[AttemptAnswer, Question] | None:
    """Serve the open question, or the next one. None = attempt finished.

    Reconnecting candidates get the same question with the original
    deadline still running. A question whose deadline passed unanswered is
    resolved as missed before the next is served.
    """
    now = _now()
    if attempt.status is AttemptStatus.COMPLETED:
        return None
    if attempt.status in (AttemptStatus.EXPIRED, AttemptStatus.INVALIDATED):
        # invalidated = superseded by a re-issued attempt; the old link is dead
        raise AttemptExpiredError
    if attempt.status is AttemptStatus.PENDING:
        if now > attempt.expires_at:
            attempt.status = AttemptStatus.EXPIRED
            await db.commit()
            raise AttemptExpiredError
        attempt.status = AttemptStatus.IN_PROGRESS
        attempt.started_at = now

    answers = await resolved_answers(db, attempt)
    open_answers = [a for a in answers if a.answered_at is None]
    for answer in open_answers:
        if now <= answer.deadline_at:
            question = (
                await db.execute(select(Question).where(Question.id == answer.question_id))
            ).scalar_one()
            await db.commit()
            return answer, question
        # deadline passed unanswered → resolve as missed
        answer.answered_at = now
        answer.answer_key = None
        answer.is_correct = False

    served_ids = {a.question_id for a in answers}
    remaining = [qid for qid in attempt.question_ids if qid not in served_ids]
    if not remaining:
        await _finalize(db, attempt)
        return None

    question = (await db.execute(select(Question).where(Question.id == remaining[0]))).scalar_one()
    option_order = list(question.options.keys())
    (rng or _default_rng).shuffle(option_order)
    answer = AttemptAnswer(
        attempt_id=attempt.id,
        question_id=question.id,
        option_order=option_order,
        served_at=now,
        deadline_at=now
        + timedelta(
            seconds=effective_time_limit(attempt, question) + settings.quiz_network_grace_seconds
        ),
    )
    db.add(answer)
    await db.commit()
    return answer, question


async def submit_answer(
    db: AsyncSession, attempt: QuizAttempt, question_id: str, answer_key: str
) -> AttemptAnswer:
    """Record an answer. Late submissions are stored but score zero."""
    if attempt.status is AttemptStatus.INVALIDATED:
        # re-issued mid-question: the superseded attempt takes no more input
        raise AttemptExpiredError
    now = _now()
    answer = (
        await db.execute(
            select(AttemptAnswer).where(
                AttemptAnswer.attempt_id == attempt.id,
                AttemptAnswer.question_id == question_id,
                AttemptAnswer.answered_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if answer is None:
        raise NoOpenQuestionError
    question = (await db.execute(select(Question).where(Question.id == question_id))).scalar_one()
    answer.answered_at = now
    answer.answer_key = answer_key
    answer.is_correct = now <= answer.deadline_at and answer_key == question.correct_key
    await db.commit()
    return answer


async def get_attempt_by_application(
    db: AsyncSession, application_id: uuid.UUID
) -> QuizAttempt | None:
    """Latest attempt by created_at — mirrors Application.quiz_attempt; older
    rows are re-issue history (attempts are 1..N per application since 0012)."""
    return (
        (
            await db.execute(
                select(QuizAttempt)
                .where(QuizAttempt.application_id == application_id)
                .order_by(QuizAttempt.created_at.desc())
                .limit(1)
            )
        )
        .scalars()
        .first()
    )


async def review_answers(
    db: AsyncSession, attempt: QuizAttempt
) -> list[tuple[AttemptAnswer, Question]]:
    """Resolved answers paired with their questions, in serve order."""
    answers = [a for a in await resolved_answers(db, attempt) if a.answered_at is not None]
    questions = {
        q.id: q
        for q in (
            await db.execute(select(Question).where(Question.id.in_(attempt.question_ids)))
        ).scalars()
    }
    return [(answer, questions[answer.question_id]) for answer in answers]


async def get_attempt_by_id(db: AsyncSession, attempt_id: uuid.UUID) -> QuizAttempt | None:
    return (
        await db.execute(select(QuizAttempt).where(QuizAttempt.id == attempt_id))
    ).scalar_one_or_none()


async def attempt_context(
    db: AsyncSession, attempt: QuizAttempt
) -> tuple[Application, Company, Job]:
    """The application (with candidate), company and job behind an attempt —
    the start-gate intro (screen 18) renders from these."""
    application = (
        await db.execute(
            select(Application)
            .where(Application.id == attempt.application_id)
            .options(
                selectinload(Application.candidate),
                selectinload(Application.job),
                selectinload(Application.quiz_attempts),
            )
        )
    ).scalar_one()
    company = (
        await db.execute(select(Company).where(Company.id == attempt.company_id))
    ).scalar_one()
    return application, company, application.job


async def practice_pool(
    db: AsyncSession, attempt: QuizAttempt, company: Company, job: Job
) -> list[Question]:
    """Questions eligible for unrecorded practice runs: the job's tag pool
    minus the attempt's frozen (real) questions. Empty when the job's pool
    has nothing to spare."""
    config = parse_quiz_config(job)
    pool = await _question_pool(db, company, config)
    frozen = set(attempt.question_ids)
    return [question for question in pool if question.id not in frozen]


async def practice_question(
    db: AsyncSession,
    attempt: QuizAttempt,
    company: Company,
    job: Job,
    *,
    rng: random.Random | None = None,
) -> Question | None:
    """One random sample question for a practice run. Nothing is recorded."""
    pool = await practice_pool(db, attempt, company, job)
    if not pool:
        return None
    return (rng or _default_rng).choice(pool)
