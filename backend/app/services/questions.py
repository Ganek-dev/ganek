from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Company, Question, QuestionSource, QuestionStatus
from app.schemas.questions import QuestionCreate, QuestionUpdate

COMPANY_QUESTION_DOMAIN = "company"


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
