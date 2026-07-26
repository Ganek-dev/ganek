import random

from fastapi import APIRouter, BackgroundTasks, HTTPException, status

from app.api.deps import DbSession, PublicCompany, SingleCompany
from app.core.config import settings
from app.core.ratelimit import rate_limit
from app.core.security import create_quiz_token, read_quiz_token
from app.models import AttemptStatus, Company, Job, QuizAttempt
from app.schemas.public import (
    ApplicationReceived,
    ApplicationSubmit,
    CvUploadTicket,
    PracticeOut,
    PracticeQuestionOut,
    PublicCompanyOut,
    PublicCompanyPage,
    PublicJobDetail,
    PublicJobSummary,
    QuizAnswerIn,
    QuizAnswerOut,
    QuizEventsIn,
    QuizEventsOut,
    QuizNextOut,
    QuizOptionOut,
    QuizQuestionOut,
    QuizStateOut,
)
from app.services import applications as applications_service
from app.services import email as email_service
from app.services import jobs as jobs_service
from app.services import quiz as quiz_service
from app.services import storage

router = APIRouter(prefix="/public", tags=["public"])

# practice options reshuffle per serve, same anti-cheat CSPRNG stance as the engine
_practice_rng = random.SystemRandom()


async def _company_page(db: DbSession, company: Company) -> PublicCompanyPage:
    jobs = await jobs_service.list_published_jobs(db, company)
    return PublicCompanyPage(
        company=PublicCompanyOut.model_validate(company),
        jobs=[PublicJobSummary.model_validate(j) for j in jobs],
    )


async def _published_job_or_404(db: DbSession, company: Company, job_slug: str) -> Job:
    job = await jobs_service.get_published_job(db, company, job_slug)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
    return job


# Multi-tenant routes (hosted): /c/{slug} pages
@router.get(
    "/companies/{slug}",
    response_model=PublicCompanyPage,
    dependencies=[rate_limit("public", lambda: settings.rate_limit_public_per_minute)],
)
async def company_page(company: PublicCompany, db: DbSession) -> PublicCompanyPage:
    return await _company_page(db, company)


@router.get(
    "/companies/{slug}/jobs/{job_slug}",
    response_model=PublicJobDetail,
    dependencies=[rate_limit("public", lambda: settings.rate_limit_public_per_minute)],
)
async def company_job(company: PublicCompany, job_slug: str, db: DbSession) -> Job:
    return await _published_job_or_404(db, company, job_slug)


# Single-tenant routes (self-host): the instance's one company at /
@router.get(
    "/company",
    response_model=PublicCompanyPage,
    dependencies=[rate_limit("public", lambda: settings.rate_limit_public_per_minute)],
)
async def single_company_page(company: SingleCompany, db: DbSession) -> PublicCompanyPage:
    return await _company_page(db, company)


@router.get(
    "/company/jobs/{job_slug}",
    response_model=PublicJobDetail,
    dependencies=[rate_limit("public", lambda: settings.rate_limit_public_per_minute)],
)
async def single_company_job(company: SingleCompany, job_slug: str, db: DbSession) -> Job:
    return await _published_job_or_404(db, company, job_slug)


def _upload_ticket(company: Company) -> CvUploadTicket:
    object_key = storage.build_cv_key(company.id)
    return CvUploadTicket(
        upload_url=storage.presign_cv_upload(object_key),
        object_key=object_key,
        content_type=storage.CV_CONTENT_TYPE,
        max_size_mb=settings.cv_max_size_mb,
    )


async def _apply(
    db: DbSession,
    company: Company,
    job_slug: str,
    payload: ApplicationSubmit,
    background: BackgroundTasks,
) -> ApplicationReceived:
    job = await _published_job_or_404(db, company, job_slug)
    try:
        application = await applications_service.submit_application(db, company, job, payload)
    except applications_service.InvalidCvError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=exc.reason
        ) from None
    except applications_service.AlreadyAppliedError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="You already applied for this position",
        ) from None
    attempt = await quiz_service.create_attempt(db, company, application, job)
    quiz_token = create_quiz_token(attempt.id) if attempt is not None else None
    if attempt is not None and quiz_token is not None:
        # assessment attached → the invite (17a) subsumes the generic confirmation
        background.add_task(
            email_service.send_quiz_invite,
            to=payload.email,
            candidate_name=payload.name,
            job_title=job.title,
            company_name=company.name,
            brand_primary=(company.theme or {}).get("primary_color"),
            quiz_url=f"{settings.public_base_url.rstrip('/')}/quiz/{quiz_token}",
            question_count=len(attempt.question_ids),
            seconds_per_question=attempt.time_limit_seconds,
            expires_at=attempt.expires_at,
        )
    else:
        background.add_task(
            email_service.send_application_received,
            to=payload.email,
            candidate_name=payload.name,
            job_title=job.title,
            company_name=company.name,
        )
    return ApplicationReceived(quiz_token=quiz_token)


@router.post(
    "/companies/{slug}/jobs/{job_slug}/apply/upload-url",
    response_model=CvUploadTicket,
    dependencies=[rate_limit("upload", lambda: settings.rate_limit_upload_per_minute)],
)
async def company_cv_upload_url(
    company: PublicCompany, job_slug: str, db: DbSession
) -> CvUploadTicket:
    await _published_job_or_404(db, company, job_slug)
    return _upload_ticket(company)


@router.post(
    "/companies/{slug}/jobs/{job_slug}/apply",
    response_model=ApplicationReceived,
    status_code=status.HTTP_201_CREATED,
    dependencies=[rate_limit("apply", lambda: settings.rate_limit_apply_per_minute)],
)
async def company_apply(
    company: PublicCompany,
    job_slug: str,
    payload: ApplicationSubmit,
    db: DbSession,
    background: BackgroundTasks,
) -> ApplicationReceived:
    return await _apply(db, company, job_slug, payload, background)


@router.post(
    "/company/jobs/{job_slug}/apply/upload-url",
    response_model=CvUploadTicket,
    dependencies=[rate_limit("upload", lambda: settings.rate_limit_upload_per_minute)],
)
async def single_cv_upload_url(
    company: SingleCompany, job_slug: str, db: DbSession
) -> CvUploadTicket:
    await _published_job_or_404(db, company, job_slug)
    return _upload_ticket(company)


@router.post(
    "/company/jobs/{job_slug}/apply",
    response_model=ApplicationReceived,
    status_code=status.HTTP_201_CREATED,
    dependencies=[rate_limit("apply", lambda: settings.rate_limit_apply_per_minute)],
)
async def single_apply(
    company: SingleCompany,
    job_slug: str,
    payload: ApplicationSubmit,
    db: DbSession,
    background: BackgroundTasks,
) -> ApplicationReceived:
    return await _apply(db, company, job_slug, payload, background)


async def _attempt_or_404(db: DbSession, token: str) -> "QuizAttempt":
    attempt_id = read_quiz_token(token)
    attempt = (
        await quiz_service.get_attempt_by_id(db, attempt_id) if attempt_id is not None else None
    )
    if attempt is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Quiz not found")
    return attempt


async def _answered_count(db: DbSession, attempt: "QuizAttempt") -> int:
    return sum(1 for a in await quiz_service.resolved_answers(db, attempt) if a.answered_at)


@router.get(
    "/quiz/{token}",
    response_model=QuizStateOut,
    dependencies=[rate_limit("quiz", lambda: settings.rate_limit_quiz_per_minute)],
)
async def quiz_state(token: str, db: DbSession) -> QuizStateOut:
    attempt = await _attempt_or_404(db, token)
    application, company, job = await quiz_service.attempt_context(db, attempt)
    practice_available = attempt.status is AttemptStatus.PENDING and bool(
        await quiz_service.practice_pool(db, attempt, company, job)
    )
    return QuizStateOut(
        status=attempt.status.value,
        answered=await _answered_count(db, attempt),
        total=len(attempt.question_ids),
        candidate_name=application.candidate.name,
        company_name=company.name,
        job_title=job.title,
        brand_primary=(company.theme or {}).get("primary_color"),
        seconds_per_question=attempt.time_limit_seconds,
        expires_at=attempt.expires_at,
        practice_available=practice_available,
    )


@router.post(
    "/quiz/{token}/practice",
    response_model=PracticeOut,
    dependencies=[rate_limit("quiz", lambda: settings.rate_limit_quiz_per_minute)],
)
async def quiz_practice(token: str, db: DbSession) -> PracticeOut:
    """Serve one sample question for an unrecorded practice run (screen 19).

    Only available before the real assessment starts; nothing is written.
    """
    attempt = await _attempt_or_404(db, token)
    if attempt.status is not AttemptStatus.PENDING:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Practice is only available before the assessment starts",
        )
    _, company, job = await quiz_service.attempt_context(db, attempt)
    question = await quiz_service.practice_question(db, attempt, company, job)
    if question is None:
        return PracticeOut(question=None)
    option_keys = list(question.options.keys())
    _practice_rng.shuffle(option_keys)
    return PracticeOut(
        question=PracticeQuestionOut(
            id=question.id,
            prompt_md=question.prompt_md,
            options=[
                QuizOptionOut(key=key, text_md=str(question.options[key])) for key in option_keys
            ],
            time_limit_seconds=quiz_service.effective_time_limit(attempt, question),
        )
    )


@router.post(
    "/quiz/{token}/next",
    response_model=QuizNextOut,
    dependencies=[rate_limit("quiz", lambda: settings.rate_limit_quiz_per_minute)],
)
async def quiz_next(token: str, db: DbSession) -> QuizNextOut:
    attempt = await _attempt_or_404(db, token)
    try:
        served = await quiz_service.current_or_next_question(db, attempt)
    except quiz_service.AttemptExpiredError:
        raise HTTPException(
            status_code=status.HTTP_410_GONE, detail="This quiz has expired"
        ) from None
    if served is None:
        return QuizNextOut(done=True)
    answer, question = served
    answered = await _answered_count(db, attempt)
    return QuizNextOut(
        done=False,
        question=QuizQuestionOut(
            id=question.id,
            prompt_md=question.prompt_md,
            options=[
                QuizOptionOut(key=key, text_md=str(question.options[key]))
                for key in answer.option_order
            ],
            time_limit_seconds=quiz_service.effective_time_limit(attempt, question),
            deadline_at=answer.deadline_at,
            index=answered + 1,
            total=len(attempt.question_ids),
        ),
    )


@router.post(
    "/quiz/{token}/answer",
    response_model=QuizAnswerOut,
    dependencies=[rate_limit("quiz", lambda: settings.rate_limit_quiz_per_minute)],
)
async def quiz_answer(token: str, payload: QuizAnswerIn, db: DbSession) -> QuizAnswerOut:
    attempt = await _attempt_or_404(db, token)
    try:
        await quiz_service.submit_answer(db, attempt, payload.question_id, payload.answer_key)
    except quiz_service.NoOpenQuestionError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This question is not open for answering",
        ) from None
    return QuizAnswerOut()


@router.post(
    "/quiz/{token}/events",
    response_model=QuizEventsOut,
    dependencies=[rate_limit("quiz", lambda: settings.rate_limit_quiz_per_minute)],
)
async def quiz_events(token: str, payload: QuizEventsIn, db: DbSession) -> QuizEventsOut:
    attempt = await _attempt_or_404(db, token)
    await quiz_service.record_events(db, attempt, [event.model_dump() for event in payload.events])
    return QuizEventsOut()
