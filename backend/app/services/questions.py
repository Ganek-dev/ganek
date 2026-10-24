from dataclasses import dataclass
from typing import Literal
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    AttemptAnswer,
    AttemptStatus,
    Company,
    Question,
    Questionnaire,
    QuestionSource,
    QuestionStatus,
    QuizAttempt,
)
from app.schemas.questions import QuestionCreate, QuestionUpdate

COMPANY_QUESTION_DOMAIN = "company"


async def list_bank_questions(
    db: AsyncSession,
    *,
    tag: str | None = None,
    difficulty: int | None = None,
    search: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[Question], int]:
    """Open-bank questions (never company-private ones) with filters + total count."""
    conditions = [Question.company_id.is_(None), Question.status == QuestionStatus.ACTIVE]
    if tag:
        conditions.append(Question.tags.contains([tag]))
    if difficulty:
        conditions.append(Question.difficulty == difficulty)
    if search:
        # `%`/`_` are ilike wildcards — searches must match them literally
        escaped = search.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        conditions.append(Question.prompt_md.ilike(f"%{escaped}%", escape="\\"))
    total = (
        await db.execute(select(func.count()).select_from(Question).where(*conditions))
    ).scalar_one()
    query = select(Question).where(*conditions).order_by(Question.id).limit(limit).offset(offset)
    return list((await db.execute(query)).scalars().all()), total


async def list_bank_tags(db: AsyncSession) -> list[str]:
    """Distinct tags across active bank questions, sorted."""
    tag_col = func.unnest(Question.tags).label("tag")
    query = (
        select(tag_col)
        .where(Question.company_id.is_(None), Question.status == QuestionStatus.ACTIVE)
        .distinct()
        .order_by("tag")
    )
    return list((await db.execute(query)).scalars().all())


async def set_bank_block(
    db: AsyncSession, company: Company, question_id: str, *, blocked: bool
) -> bool:
    """Add/remove a bank question id on the company-wide blocklist. False = no such question."""
    exists = (
        await db.execute(
            select(Question.id).where(Question.id == question_id, Question.company_id.is_(None))
        )
    ).scalar_one_or_none()
    if exists is None:
        return False
    current = set(company.blocked_question_ids or [])
    updated = current | {question_id} if blocked else current - {question_id}
    if updated != current:
        company.blocked_question_ids = sorted(updated)  # reassign: ARRAY isn't mutation-tracked
        await db.commit()
    return True


async def list_company_questions(db: AsyncSession, company: Company) -> list[Question]:
    query = (
        select(Question)
        .where(Question.company_id == company.id)
        .order_by(Question.created_at.desc())
    )
    return list((await db.execute(query)).scalars().all())


async def get_company_question(
    db: AsyncSession, company: Company, question_id: str
) -> Question | None:
    return (
        await db.execute(
            select(Question).where(Question.company_id == company.id, Question.id == question_id)
        )
    ).scalar_one_or_none()


async def create_company_question(
    db: AsyncSession, company: Company, payload: QuestionCreate
) -> Question:
    question = Question(
        id=f"co-{uuid4().hex[:16]}",
        company_id=company.id,
        domain=COMPANY_QUESTION_DOMAIN,
        source=QuestionSource.COMPANY,
        **payload.model_dump(),
    )
    db.add(question)
    await db.commit()
    return question


async def update_company_question(
    db: AsyncSession, question: Question, payload: QuestionUpdate
) -> Question:
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(question, field, value)
    await db.commit()
    await db.refresh(question)
    return question


async def retire_company_question(db: AsyncSession, question: Question) -> Question:
    question.status = QuestionStatus.RETIRED
    await db.commit()
    await db.refresh(question)
    return question


MAX_RESOLVE_IDS = 300


async def questionnaire_usage_counts(
    db: AsyncSession, company: Company, ids: list[str]
) -> dict[str, int]:
    """For each requested id, how many of the workspace's questionnaires
    reference it. Recruiters use this before retiring/blocking to see
    what would be affected."""
    unique_ids = [qid for qid in dict.fromkeys(ids) if qid]
    if not unique_ids:
        return {}
    # unnest is a set-returning function, so it can't be filtered in
    # HAVING — unnest in a subquery and filter with a plain WHERE.
    refs = (
        select(func.unnest(Questionnaire.question_refs).label("ref"))
        .where(Questionnaire.company_id == company.id)
        .subquery()
    )
    query = (
        select(refs.c.ref, func.count().label("n"))
        .where(refs.c.ref.in_(unique_ids[:MAX_RESOLVE_IDS]))
        .group_by(refs.c.ref)
    )
    rows = (await db.execute(query)).all()
    counts = {row.ref: int(row.n) for row in rows}
    # 0 counts stay implicit — the frontend treats a missing key as zero
    return counts


async def resolve_questions(db: AsyncSession, company: Company, ids: list[str]) -> list[Question]:
    """Fetch Question rows visible to this workspace for the given ids —
    bank rows and this company's own questions (active OR retired), in
    the order requested. Missing / cross-tenant refs are silently
    omitted; the caller can diff against its ref list to spot gaps and
    render retired refs with a warning."""
    unique_ids = [qid for qid in dict.fromkeys(ids) if qid]
    if not unique_ids:
        return []
    rows = (
        (
            await db.execute(
                select(Question).where(
                    Question.id.in_(unique_ids[:MAX_RESOLVE_IDS]),
                    (Question.company_id.is_(None)) | (Question.company_id == company.id),
                )
            )
        )
        .scalars()
        .all()
    )
    by_id = {q.id: q for q in rows}
    return [by_id[qid] for qid in unique_ids if qid in by_id]


# --- difficulty calibration from real answers ----------------------------------
#
# A report, never an input to scoring or selection (no-ML rule): per question,
# over THIS workspace's completed attempts, how candidates actually did. The
# hint is a fixed rule a human can check: with at least CALIBRATION_MIN_SAMPLE
# answers, a correct rate more than CALIBRATION_MARGIN outside the band its
# rating usually lands in says "easier" or "harder". Ratings change only
# through a questions: PR.

CALIBRATION_MIN_SAMPLE = 20
CALIBRATION_MARGIN = 0.10
CALIBRATION_BANDS: dict[int, tuple[float, float]] = {
    1: (0.85, 1.0),
    2: (0.70, 0.85),
    3: (0.50, 0.70),
    4: (0.30, 0.50),
    5: (0.0, 0.30),
}


CalibrationHint = Literal["easier", "harder"]


def calibration_hint(difficulty: int, *, served: int, correct: int) -> CalibrationHint | None:
    if served < CALIBRATION_MIN_SAMPLE:
        return None
    low, high = CALIBRATION_BANDS.get(difficulty, (0.0, 1.0))
    # whole percentage points: 80% on a 50-70 band is exactly at the margin, not past it
    rate_pct = round(100 * correct / served)
    margin_pct = round(100 * CALIBRATION_MARGIN)
    if high < 1.0 and rate_pct > round(100 * high) + margin_pct:
        return "easier"
    if low > 0.0 and rate_pct < round(100 * low) - margin_pct:
        return "harder"
    return None


@dataclass
class AnswerStats:
    difficulty: int
    served: int = 0
    correct: int = 0
    timed_out: int = 0
    answered: int = 0
    response_ms_total: int = 0

    @property
    def correct_rate(self) -> float:
        return self.correct / self.served if self.served else 0.0

    @property
    def timeout_rate(self) -> float:
        return self.timed_out / self.served if self.served else 0.0

    @property
    def avg_response_ms(self) -> int | None:
        return round(self.response_ms_total / self.answered) if self.answered else None

    @property
    def hint(self) -> CalibrationHint | None:
        return calibration_hint(self.difficulty, served=self.served, correct=self.correct)


async def answer_stats(
    db: AsyncSession, company: Company, ids: list[str]
) -> dict[str, AnswerStats]:
    """Per-question answer stats over this company's COMPLETED attempts.
    Invalidated and expired runs carry no evidence. Ids never served here
    are absent from the result."""
    if not ids:
        return {}
    difficulties: dict[str, int] = {
        question_id: difficulty
        for question_id, difficulty in (
            await db.execute(select(Question.id, Question.difficulty).where(Question.id.in_(ids)))
        ).all()
    }
    rows = (
        await db.execute(
            select(
                AttemptAnswer.question_id,
                AttemptAnswer.is_correct,
                AttemptAnswer.answer_key,
                AttemptAnswer.served_at,
                AttemptAnswer.answered_at,
            )
            .join(QuizAttempt, AttemptAnswer.attempt_id == QuizAttempt.id)
            .where(
                QuizAttempt.company_id == company.id,
                QuizAttempt.status == AttemptStatus.COMPLETED,
                AttemptAnswer.question_id.in_(ids),
                AttemptAnswer.answered_at.is_not(None),
            )
        )
    ).all()
    stats: dict[str, AnswerStats] = {}
    for question_id, is_correct, answer_key, served_at, answered_at in rows:
        if answered_at is None:  # filtered in SQL; narrows the type for SQLAlchemy 2.1
            continue
        entry = stats.setdefault(
            question_id, AnswerStats(difficulty=difficulties.get(question_id, 3))
        )
        entry.served += 1
        if answer_key is None:
            entry.timed_out += 1
            continue
        entry.answered += 1
        entry.response_ms_total += int((answered_at - served_at).total_seconds() * 1000)
        if is_correct:
            entry.correct += 1
    return stats
