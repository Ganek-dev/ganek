from fastapi import APIRouter, HTTPException, Query, status

from app.api.deps import AdminUser, CurrentCompany, DbSession
from app.models import Question
from app.schemas.questions import (
    BankQuestionOut,
    BankQuestionPage,
    QuestionCreate,
    QuestionOut,
    QuestionUpdate,
    ResolvedQuestion,
)
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


@router.get("/bank", response_model=BankQuestionPage)
async def browse_bank(
    db: DbSession,
    company: CurrentCompany,
    tag: str | None = None,
    difficulty: int | None = Query(default=None, ge=1, le=5),
    q: str | None = Query(default=None, max_length=200),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> BankQuestionPage:
    """Browse the open question bank the way quizzes will draw from it."""
    items, total = await questions_service.list_bank_questions(
        db, tag=tag, difficulty=difficulty, search=q, limit=limit, offset=offset
    )
    blocked = set(company.blocked_question_ids or [])
    return BankQuestionPage(
        items=[
            BankQuestionOut(
                id=question.id,
                domain=question.domain,
                prompt_md=question.prompt_md,
                options=question.options,
                correct_key=question.correct_key,
                explanation_md=question.explanation_md,
                tags=question.tags,
                difficulty=question.difficulty,
                time_limit_seconds=question.time_limit_seconds,
                blocked=question.id in blocked,
            )
            for question in items
        ],
        total=total,
        tags=await questions_service.list_bank_tags(db),
    )


@router.get("/resolve", response_model=list[ResolvedQuestion])
async def resolve_questions(
    db: DbSession,
    company: CurrentCompany,
    ids: str = Query(
        default="",
        max_length=8000,
        description="Comma-separated question ids (bank slugs and/or company UUIDs)",
    ),
) -> list[ResolvedQuestion]:
    """Resolve question refs to metadata for the questionnaire builder.

    Order matches the request; missing/unauthorized/retired refs are omitted
    so the caller can diff against its own list to detect gaps.
    """
    id_list = [qid.strip() for qid in ids.split(",") if qid.strip()]
    rows = await questions_service.resolve_questions(db, company, id_list)
    blocked = set(company.blocked_question_ids or [])
    return [
        ResolvedQuestion(
            id=question.id,
            prompt_md=question.prompt_md,
            tags=question.tags,
            difficulty=question.difficulty,
            time_limit_seconds=question.time_limit_seconds,
            source=question.source,
            status=question.status,
            blocked=question.id in blocked,
        )
        for question in rows
    ]


@router.put("/bank/{question_id}/block", status_code=status.HTTP_204_NO_CONTENT)
async def block_bank_question(
    question_id: str, db: DbSession, company: CurrentCompany, _admin: AdminUser
) -> None:
    """Company-wide: never serve this bank question in any of our quizzes."""
    if not await questions_service.set_bank_block(db, company, question_id, blocked=True):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Question not found")


@router.delete("/bank/{question_id}/block", status_code=status.HTTP_204_NO_CONTENT)
async def unblock_bank_question(
    question_id: str, db: DbSession, company: CurrentCompany, _admin: AdminUser
) -> None:
    if not await questions_service.set_bank_block(db, company, question_id, blocked=False):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Question not found")


@router.post("", response_model=QuestionOut, status_code=status.HTTP_201_CREATED)
async def create_question(
    payload: QuestionCreate, db: DbSession, company: CurrentCompany, _admin: AdminUser
) -> Question:
    return await questions_service.create_company_question(db, company, payload)


@router.patch("/{question_id}", response_model=QuestionOut)
async def update_question(
    question_id: str,
    payload: QuestionUpdate,
    db: DbSession,
    company: CurrentCompany,
    _admin: AdminUser,
) -> Question:
    question = await _get_or_404(db, company, question_id)
    return await questions_service.update_company_question(db, question, payload)


@router.delete("/{question_id}", response_model=QuestionOut)
async def retire_question(
    question_id: str, db: DbSession, company: CurrentCompany, _admin: AdminUser
) -> Question:
    """Retire (never hard-delete): attempts may reference the question."""
    question = await _get_or_404(db, company, question_id)
    return await questions_service.retire_company_question(db, question)
