import uuid

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Company, Questionnaire
from app.schemas.questionnaires import QuestionnaireCreate, QuestionnaireUpdate


class DuplicateNameError(Exception):
    def __init__(self, name: str) -> None:
        super().__init__(f"a questionnaire named {name!r} already exists")
        self.name = name


async def list_questionnaires(db: AsyncSession, company: Company) -> list[Questionnaire]:
    query = (
        select(Questionnaire)
        .where(Questionnaire.company_id == company.id)
        .order_by(Questionnaire.created_at.desc())
    )
    return list((await db.execute(query)).scalars().all())


async def get_questionnaire(
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


async def create_questionnaire(
    db: AsyncSession, company: Company, payload: QuestionnaireCreate
) -> Questionnaire:
    questionnaire = Questionnaire(company_id=company.id, **payload.model_dump())
    db.add(questionnaire)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise DuplicateNameError(payload.name) from None
    return questionnaire


async def update_questionnaire(
    db: AsyncSession, questionnaire: Questionnaire, payload: QuestionnaireUpdate
) -> Questionnaire:
    values = payload.model_dump(exclude_unset=True)
    for field, value in values.items():
        setattr(questionnaire, field, value)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise DuplicateNameError(questionnaire.name) from None
    await db.refresh(questionnaire)
    return questionnaire


async def delete_questionnaire(db: AsyncSession, questionnaire: Questionnaire) -> None:
    await db.delete(questionnaire)
    await db.commit()
