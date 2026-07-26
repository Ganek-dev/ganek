from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Company, Question, Questionnaire, QuestionSource, QuestionStatus
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
        conditions.append(Question.prompt_md.ilike(f"%{search}%"))
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
