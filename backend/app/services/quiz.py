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
