import random
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, BackgroundTasks, HTTPException, Response, status
from sqlalchemy import select

from app.api.auth import _set_session_cookie
from app.api.deps import DbSession, PublicCompany, SingleCompany
from app.core.config import settings
from app.core.ratelimit import rate_limit
from app.core.security import (
    create_quiz_token,
    create_status_token,
    read_quiz_token,
    read_status_token,
)
from app.models import (
    Application,
    ApplicationStage,
    AttemptStatus,
    Company,
    Job,
    QuizAttempt,
    UserInvite,
)
from app.schemas.auth import UserOut
from app.schemas.public import (
    ApplicationReceived,
    ApplicationStatusOut,
    ApplicationSubmit,
    CvUploadTicket,
    JobsFeed,
    JobsFeedItem,
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
    StatusQuizOut,
)
from app.schemas.users import InviteAcceptRequest, PublicInviteOut
from app.services import applications as applications_service
from app.services import email as email_service
from app.services import invites as invites_service
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


async def _jobs_feed(db: DbSession, company: Company, response: Response) -> JobsFeed:
    """Published roles as third-party-friendly JSON (screen 25).

    Meant for company marketing sites: open CORS and a short shared-cache
    TTL (the security middleware's no-store applies to everything else on
    /api/v1 via setdefault, so these explicit headers win).
    """
    base = settings.public_base_url.rstrip("/")
    prefix = f"{base}/jobs" if settings.mode == "single" else f"{base}/c/{company.slug}/jobs"
    jobs = await jobs_service.list_published_jobs(db, company)
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Cache-Control"] = "public, max-age=60"
    return JobsFeed(
        company=company.name,
        brand_primary=(company.theme or {}).get("primary_color"),
        jobs=[
            JobsFeedItem(
                title=job.title,
                slug=job.slug,
                location=job.location,
                remote_policy=job.remote_policy,
                employment_type=job.employment_type,
                tags=job.tags,
                apply_url=f"{prefix}/{job.slug}",
                posted_at=job.published_at,
            )
            for job in jobs
        ],
    )


@router.get(
    "/companies/{slug}/jobs-feed",
    response_model=JobsFeed,
    dependencies=[rate_limit("public", lambda: settings.rate_limit_public_per_minute)],
)
async def company_jobs_feed(company: PublicCompany, db: DbSession, response: Response) -> JobsFeed:
    return await _jobs_feed(db, company, response)


@router.get(
    "/company/jobs-feed",
    response_model=JobsFeed,
    dependencies=[rate_limit("public", lambda: settings.rate_limit_public_per_minute)],
)
async def single_jobs_feed(company: SingleCompany, db: DbSession, response: Response) -> JobsFeed:
    return await _jobs_feed(db, company, response)


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
    return ApplicationReceived(
        quiz_token=quiz_token, status_token=create_status_token(application.id)
    )


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
        status_token=create_status_token(attempt.application_id),
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


@router.post(
    "/quiz/{token}/request-reissue",
    response_model=dict[str, bool],
    dependencies=[rate_limit("quiz", lambda: settings.rate_limit_quiz_per_minute)],
)
async def quiz_request_reissue(
    token: str, db: DbSession, background: BackgroundTasks
) -> dict[str, bool]:
    """Expired-link screen (27c): ask for a fresh assessment link.

    Company setting ``quiz_expired_reissue`` decides: 'auto' re-issues a
    fresh attempt once (email delivery only — the new token is never
    returned to the caller of an old link); 'manual' (default) records
    the request for the team to act on. The lateness stays visible either
    way — the fresh attempt carries reason='expired', the manual request
    lands in the expired attempt's integrity.
    """
    attempt = await _attempt_or_404(db, token)
    now = datetime.now(UTC)
    if attempt.status is AttemptStatus.PENDING and now > attempt.expires_at:
        attempt.status = AttemptStatus.EXPIRED
        await db.commit()
    if attempt.status is AttemptStatus.INVALIDATED:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A new link was already issued — check your inbox",
        )
    if attempt.status is not AttemptStatus.EXPIRED:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This assessment link is still active",
        )
    application, company, job = await quiz_service.attempt_context(db, attempt)
    latest = application.quiz_attempt
    if latest is not None and latest.id != attempt.id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A new link was already issued — check your inbox",
        )

    mode = (company.settings or {}).get("quiz_expired_reissue", "manual")
    auto_used = any(
        (prior.integrity or {}).get("reissue", {}).get("mode") == "auto"
        for prior in application.quiz_attempts
    )
    if mode == "auto" and not auto_used:
        fresh = await quiz_service.reissue_attempt(
            db, company, application, job, reason="expired", mode="auto", by_user_id=None
        )
        if fresh is not None:
            background.add_task(
                email_service.send_quiz_invite,
                to=application.candidate.email,
                candidate_name=application.candidate.name,
                job_title=job.title,
                company_name=company.name,
                brand_primary=(company.theme or {}).get("primary_color"),
                quiz_url=f"{settings.public_base_url.rstrip('/')}/quiz/"
                f"{create_quiz_token(fresh.id)}",
                question_count=len(fresh.question_ids),
                seconds_per_question=fresh.time_limit_seconds,
                expires_at=fresh.expires_at,
            )
            return {"reissued": True}

    await quiz_service.record_reissue_request(db, attempt)
    return {"reissued": False}


DECISION_WINDOW = timedelta(days=14)  # "you'll hear back within two weeks of applying"


async def _application_by_status_token_or_404(db: DbSession, token: str) -> Application:
    application_id = read_status_token(token)
    application = (
        await applications_service.get_application_by_id(db, application_id)
        if application_id is not None
        else None
    )
    if application is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Application not found")
    return application


@router.get(
    "/applications/{token}",
    response_model=ApplicationStatusOut,
    dependencies=[rate_limit("public", lambda: settings.rate_limit_public_per_minute)],
)
async def application_status(token: str, db: DbSession) -> ApplicationStatusOut:
    """Candidate status page (screen 21) behind its signed magic-link token."""
    application = await _application_by_status_token_or_404(db, token)
    company = (
        await db.execute(select(Company).where(Company.id == application.company_id))
    ).scalar_one()
    attempt = application.quiz_attempt
    quiz = (
        StatusQuizOut(
            status=attempt.status.value,
            answered=await _answered_count(db, attempt),
            total=len(attempt.question_ids),
            completed_at=attempt.completed_at,
        )
        if attempt is not None
        else None
    )
    return ApplicationStatusOut(
        company_name=company.name,
        brand_primary=(company.theme or {}).get("primary_color"),
        job_title=application.job.title,
        candidate_name=application.candidate.name,
        cv_filename=application.cv_filename,
        applied_at=application.created_at,
        stage=application.stage.value,
        quiz=quiz,
        decision_expected_by=application.created_at + DECISION_WINDOW,
    )


@router.post(
    "/applications/{token}/withdraw",
    response_model=dict[str, bool],
    dependencies=[rate_limit("public", lambda: settings.rate_limit_public_per_minute)],
)
async def withdraw_application(token: str, db: DbSession) -> dict[str, bool]:
    """Candidate-initiated withdrawal. Decided applications stay decided."""
    application = await _application_by_status_token_or_404(db, token)
    if application.stage in (ApplicationStage.HIRED, ApplicationStage.REJECTED):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This application already has a decision",
        )
    if application.stage is not ApplicationStage.WITHDRAWN:
        application.stage = ApplicationStage.WITHDRAWN
        await db.commit()
    return {"withdrawn": True}


async def _invite_by_token_or_error(db: DbSession, token: str) -> UserInvite:
    """Resolve a team-invite token: 404 unknown/revoked, 410 past deadline."""
    invite = await invites_service.invite_by_token(db, token)
    if invite is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invite not found")
    if invite.expires_at <= datetime.now(UTC):
        raise HTTPException(status_code=status.HTTP_410_GONE, detail="This invite has expired")
    return invite


@router.get(
    "/invites/{token}",
    response_model=PublicInviteOut,
    dependencies=[rate_limit("public", lambda: settings.rate_limit_public_per_minute)],
)
async def invite_info(token: str, db: DbSession) -> PublicInviteOut:
    """Accept-page context: who's being invited where, before any account exists."""
    invite = await _invite_by_token_or_error(db, token)
    return PublicInviteOut(
        email=invite.email,
        company_name=invite.company.name,
        role=invite.role,
    )


@router.post(
    "/invites/{token}/accept",
    response_model=UserOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[rate_limit("auth", lambda: settings.rate_limit_auth_per_minute)],
)
async def accept_invite(
    token: str, payload: InviteAcceptRequest, response: Response, db: DbSession
) -> UserOut:
    """Create the invited user, consume the invite, and log the new user in."""
    invite = await _invite_by_token_or_error(db, token)
    try:
        user = await invites_service.accept_invite(db, invite, payload.password)
    except invites_service.InviteExpiredError:
        raise HTTPException(
            status_code=status.HTTP_410_GONE, detail="This invite has expired"
        ) from None
    except invites_service.EmailTakenError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with this email already exists",
        ) from None
    _set_session_cookie(response, user)
    return UserOut.model_validate(user)
