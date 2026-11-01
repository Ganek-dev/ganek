"""Reads behind the reviewer judging view (spec 4.5). Access is decided in
``app.core.access``; everything here assumes the caller holds a grant."""

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.access import granted_application_ids
from app.models import (
    Application,
    AttemptAnswer,
    AttemptStatus,
    Company,
    Interview,
    InterviewStatus,
    Question,
    Scorecard,
    User,
)
from app.schemas.public import StatusScreeningAnswer
from app.schemas.review import (
    QuizOutcome,
    ReviewApplicationListItem,
    ReviewApplicationOut,
    ReviewInterview,
    ReviewQuizQuestion,
    ReviewQuizSummary,
)
from app.schemas.scorecards import ScorecardOut
from app.services import quiz as quiz_service
from app.services import scorecards as scorecards_service
from app.services import storage


async def list_applications(db: AsyncSession, user: User) -> list[ReviewApplicationListItem]:
    granted = await granted_application_ids(db, user)
    if not granted:
        return []
    applications = (
        (
            await db.execute(
                select(Application)
                .where(Application.company_id == user.company_id, Application.id.in_(granted))
                .options(selectinload(Application.candidate), selectinload(Application.job))
                .order_by(Application.created_at.desc(), Application.id)
            )
        )
        .scalars()
        .all()
    )
    rows = {
        row.application_id: row
        for row in (
            await db.execute(
                select(Scorecard).where(
                    Scorecard.company_id == user.company_id,
                    Scorecard.reviewer_user_id == user.id,
                    Scorecard.application_id.in_(granted),
                    Scorecard.dismissed_at.is_(None),
                )
            )
        ).scalars()
    }
    starts = dict(
        (
            await db.execute(
                select(Interview.application_id, Interview.scheduled_start).where(
                    Interview.company_id == user.company_id,
                    Interview.interviewer_user_id == user.id,
                    Interview.application_id.in_(granted),
                    Interview.status != InterviewStatus.CANCELLED,
                    Interview.scheduled_start.is_not(None),
                )
            )
        )
        .tuples()
        .all()
    )
    items: list[ReviewApplicationListItem] = []
    for application in applications:
        row = rows.get(application.id)
        items.append(
            ReviewApplicationListItem(
                application_id=application.id,
                candidate_name=application.candidate.name,
                job_title=application.job.title,
                stage_label=application.stage.value.capitalize(),
                scorecard_state=scorecards_service.state_of(row) if row else None,
                scorecard_due_from=row.due_from if row else None,
                interview_start=starts.get(application.id),
            )
        )
    return items


async def _quiz_summary(db: AsyncSession, application: Application) -> ReviewQuizSummary | None:
    """The latest attempt once completed, from resolved answers only, in serve
    order. A live attempt or an expired one (never started, so no score and no
    answers) has no summary: a prompt the candidate has not been served may
    still reach them through a re-issue. Only the prompt column is ever read."""
    attempt = await quiz_service.get_attempt_by_application(db, application.id)
    if attempt is None or attempt.status is not AttemptStatus.COMPLETED:
        return None
    answers = [a for a in await quiz_service.resolved_answers(db, attempt) if a.answered_at]
    prompts = dict(
        (
            await db.execute(
                select(Question.id, Question.prompt_md).where(
                    Question.id.in_([a.question_id for a in answers]),
                    (Question.company_id.is_(None))
                    | (Question.company_id == application.company_id),
                )
            )
        )
        .tuples()
        .all()
    )
    questions = [
        ReviewQuizQuestion(prompt=prompts[answer.question_id], outcome=_outcome(answer))
        for answer in answers
        if answer.question_id in prompts
    ]
    return ReviewQuizSummary(
        score=attempt.score,
        correct=sum(1 for q in questions if q.outcome == "correct"),
        total=len(questions),
        timed_out=sum(1 for q in questions if q.outcome == "timed_out"),
        questions=questions,
    )


def _outcome(answer: AttemptAnswer) -> QuizOutcome:
    # a resolved row with no key ran out of time
    if answer.answer_key is None:
        return "timed_out"
    return "correct" if answer.is_correct else "wrong"


async def _own_interview(
    db: AsyncSession, user: User, application: Application
) -> ReviewInterview | None:
    interview = (
        await db.execute(
            select(Interview).where(
                Interview.company_id == application.company_id,
                Interview.application_id == application.id,
                Interview.interviewer_user_id == user.id,
                Interview.status != InterviewStatus.CANCELLED,
                Interview.scheduled_start.is_not(None),
            )
        )
    ).scalar_one_or_none()
    if interview is None:
        return None
    return ReviewInterview(
        scheduled_start=interview.scheduled_start,
        duration_minutes=interview.duration_minutes,
        location=interview.location or None,
        timezone=interview.timezone,
    )


async def judging_view(
    db: AsyncSession, company: Company, user: User, application: Application
) -> ReviewApplicationOut:
    """``application`` must come from the tenancy-scoped query with candidate
    and job loaded. A dismissed row is no row: it grants nothing and has no
    content, so it never counts as ``mine``."""
    rows = await scorecards_service.list_for_application(
        db, company_id=company.id, application_id=application.id
    )
    live = [row for row in rows if row.dismissed_at is None]
    mine = next((row for row in live if row.reviewer_user_id == user.id), None)
    unlocked = mine is not None and scorecards_service.state_of(mine) == "submitted"
    others = (
        [row for row in live if row is not mine and scorecards_service.state_of(row) == "submitted"]
        if unlocked
        else []
    )
    now = datetime.now(UTC)
    return ReviewApplicationOut(
        application_id=application.id,
        candidate_name=application.candidate.name,
        job_title=application.job.title,
        cv_url=(
            storage.presign_cv_download(application.cv_object_key, application.cv_filename)
            if application.cv_object_key
            else None
        ),
        screening_answers=[
            StatusScreeningAnswer(prompt=answer["prompt"], answer=answer["answer"])
            for answer in application.screening_answers
        ],
        quiz=await _quiz_summary(db, application),
        interview=await _own_interview(db, user, application),
        mine=ScorecardOut.from_row(mine, user, now=now) if mine else None,
        others=[ScorecardOut.from_row(row, user, now=now) for row in others],
        hidden_until_submitted=not unlocked,
    )
