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

from app.core.config import settings
from app.models import (
    Application,
    AttemptAnswer,
    AttemptStatus,
    Company,
    Job,
    Question,
    QuestionStatus,
    QuizAttempt,
)

# Selection/shuffle order is an anti-cheat surface: use a CSPRNG by default.
_default_rng: random.Random = random.SystemRandom()


class QuizError(Exception):
    pass


class AttemptExpiredError(QuizError):
    """The attempt was not started within its TTL."""


class NoOpenQuestionError(QuizError):
    """An answer arrived for a question that is not currently open."""


@dataclass(frozen=True)
class QuizConfig:
    enabled: bool = False
    tags: list[str] = field(default_factory=list)
    question_count: int = 6
    include_company_questions: bool = True


def parse_quiz_config(job: Job) -> QuizConfig:
    raw = job.quiz_config or {}
    tags = raw.get("tags") or job.tags
    return QuizConfig(
        enabled=bool(raw.get("enabled", False)),
        tags=list(tags),
        question_count=int(raw.get("question_count", 6)),
        include_company_questions=bool(raw.get("include_company_questions", True)),
    )


def _now() -> datetime:
    return datetime.now(UTC)


async def _question_pool(db: AsyncSession, company: Company, config: QuizConfig) -> list[Question]:
    query = select(Question).where(
        Question.status == QuestionStatus.ACTIVE,
        Question.tags.overlap(config.tags),
    )
    if config.include_company_questions:
        query = query.where((Question.company_id.is_(None)) | (Question.company_id == company.id))
    else:
        query = query.where(Question.company_id.is_(None))
    return list((await db.execute(query)).scalars().all())


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
    if not config.enabled or not config.tags:
        return None
    pool = await _question_pool(db, company, config)
    question_ids = stratified_sample(pool, config.tags, config.question_count, rng or _default_rng)
    if not question_ids:
        return None
    attempt = QuizAttempt(
        company_id=company.id,
        application_id=application.id,
        question_ids=question_ids,
        expires_at=_now() + timedelta(hours=settings.quiz_start_ttl_hours),
    )
    db.add(attempt)
    await db.commit()
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
    await db.commit()


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
    if attempt.status is AttemptStatus.EXPIRED:
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
        + timedelta(seconds=question.time_limit_seconds + settings.quiz_network_grace_seconds),
    )
    db.add(answer)
    await db.commit()
    return answer, question


async def submit_answer(
    db: AsyncSession, attempt: QuizAttempt, question_id: str, answer_key: str
) -> AttemptAnswer:
    """Record an answer. Late submissions are stored but score zero."""
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


async def get_attempt_by_id(db: AsyncSession, attempt_id: uuid.UUID) -> QuizAttempt | None:
    return (
        await db.execute(select(QuizAttempt).where(QuizAttempt.id == attempt_id))
    ).scalar_one_or_none()
