import uuid

from fastapi import APIRouter, HTTPException, status

from app.api.deps import CurrentCompany, DbSession
from app.models import Questionnaire
from app.schemas.questionnaires import (
    QuestionnaireCreate,
    QuestionnaireOut,
    QuestionnaireUpdate,
)
from app.services import questionnaires as questionnaires_service

router = APIRouter(prefix="/questionnaires", tags=["questionnaires"])


async def _get_or_404(
    db: DbSession, company: CurrentCompany, questionnaire_id: uuid.UUID
) -> Questionnaire:
    questionnaire = await questionnaires_service.get_questionnaire(db, company, questionnaire_id)
    if questionnaire is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Questionnaire not found")
    return questionnaire


@router.get("", response_model=list[QuestionnaireOut])
async def list_questionnaires(db: DbSession, company: CurrentCompany) -> list[Questionnaire]:
    return await questionnaires_service.list_questionnaires(db, company)


@router.post("", response_model=QuestionnaireOut, status_code=status.HTTP_201_CREATED)
async def create_questionnaire(
    payload: QuestionnaireCreate, db: DbSession, company: CurrentCompany
) -> Questionnaire:
    try:
        return await questionnaires_service.create_questionnaire(db, company, payload)
    except questionnaires_service.DuplicateNameError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from None


@router.get("/{questionnaire_id}", response_model=QuestionnaireOut)
async def get_questionnaire(
    questionnaire_id: uuid.UUID, db: DbSession, company: CurrentCompany
) -> Questionnaire:
    return await _get_or_404(db, company, questionnaire_id)


@router.patch("/{questionnaire_id}", response_model=QuestionnaireOut)
async def update_questionnaire(
    questionnaire_id: uuid.UUID,
    payload: QuestionnaireUpdate,
    db: DbSession,
    company: CurrentCompany,
) -> Questionnaire:
    questionnaire = await _get_or_404(db, company, questionnaire_id)
    try:
        return await questionnaires_service.update_questionnaire(db, questionnaire, payload)
    except questionnaires_service.DuplicateNameError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from None


@router.delete("/{questionnaire_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_questionnaire(
    questionnaire_id: uuid.UUID, db: DbSession, company: CurrentCompany
) -> None:
    questionnaire = await _get_or_404(db, company, questionnaire_id)
    await questionnaires_service.delete_questionnaire(db, questionnaire)
