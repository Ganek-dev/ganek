from fastapi import APIRouter, HTTPException, status

from app.api.deps import CurrentCompany, DbSession
from app.models import Question
from app.schemas.questions import QuestionCreate, QuestionOut, QuestionUpdate
from app.services import questions as questions_service

router = APIRouter(prefix="/questions", tags=["questions"])


async def _get_or_404(db: DbSession, company: CurrentCompany, question_id: str) -> Question:
    question = await questions_service.get_company_question(db, company, question_id)
    if question is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Question not found")
    return question


@router.get("", response_model=list[QuestionOut])
async def list_questions(db: DbSession, company: CurrentCompany) -> list[Question]:
    return await questions_service.list_company_questions(db, company)


@router.post("", response_model=QuestionOut, status_code=status.HTTP_201_CREATED)
async def create_question(
    payload: QuestionCreate, db: DbSession, company: CurrentCompany
) -> Question:
    return await questions_service.create_company_question(db, company, payload)


@router.patch("/{question_id}", response_model=QuestionOut)
async def update_question(
    question_id: str, payload: QuestionUpdate, db: DbSession, company: CurrentCompany
) -> Question:
    question = await _get_or_404(db, company, question_id)
    return await questions_service.update_company_question(db, question, payload)


@router.delete("/{question_id}", response_model=QuestionOut)
async def retire_question(question_id: str, db: DbSession, company: CurrentCompany) -> Question:
    """Retire (never hard-delete): attempts may reference the question."""
    question = await _get_or_404(db, company, question_id)
    return await questions_service.retire_company_question(db, question)
