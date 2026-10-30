import random
from datetime import UTC, date, datetime, timedelta

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request, Response, status
from sqlalchemy import select

from app.api.auth import _set_session_cookie
from app.api.deps import DbSession, PublicCompany, SingleCompany
from app.core import challenge, urls
from app.core.config import settings
from app.core.ratelimit import rate_limit
from app.core.security import (
    create_quiz_token,
    create_status_token,
    read_interview_token,
    read_preview_token,
    read_quiz_token,
    read_status_token,
)
from app.models import (
    Application,
    ApplicationStage,
    AttemptStatus,
    Company,
    Interview,
    InterviewStatus,
    Job,
    JobStatus,
    QuizAttempt,
    Task,
    UserInvite,
)
from app.schemas.auth import UserOut
from app.schemas.public import (
    ApplicationReceived,
    ApplicationStatusOut,
    ApplicationSubmit,
    CvUploadTicket,
    InterviewPublicOut,
    InterviewSlotBody,
    JobsFeed,
    JobsFeedItem,
    PracticeOut,
    PracticeQuestionOut,
    PrivacyRequestReceipt,
    PublicCompanyOut,
    PublicCompanyPage,
    PublicJobDetail,
    PublicJobSummary,
    PublicPrivacyNotice,
    QuizAnswerIn,
    QuizAnswerOut,
    QuizEventsIn,
    QuizEventsOut,
    QuizNextOut,
    QuizOptionOut,
    QuizQuestionOut,
    QuizStateOut,
    ReissueRequest,
    StatusQuizOut,
)
from app.schemas.users import InviteAcceptRequest, PublicInviteOut
from app.services import activity, demo_mode, google_calendar, quotas, rejection_reasons, storage
from app.services import applications as applications_service
from app.services import company as company_service
from app.services import interviews as interviews_service
from app.services import invites as invites_service
from app.services import jobs as jobs_service
from app.services import outbox as outbox_service
from app.services import quiz as quiz_service
from app.services import views as views_service

router = APIRouter(prefix="/public", tags=["public"])


def _quota_429(exc: quotas.QuotaExceeded) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        detail="This employer has reached its limit for now - please try again later",
        headers={"Retry-After": str(exc.retry_after)},
    )


# practice options reshuffle per serve, same anti-cheat CSPRNG stance as the engine
_practice_rng = random.SystemRandom()


async def _company_page(db: DbSession, company: Company) -> PublicCompanyPage:
    jobs = await jobs_service.list_published_jobs(db, company)
    return PublicCompanyPage(
        company=PublicCompanyOut.model_validate(company),
        jobs=[PublicJobSummary.model_validate(j) for j in jobs],
    )


async def _published_job_or_404(
    db: DbSession, company: Company, job_slug: str, preview: str | None = None
) -> Job:
    """The published job, or an unpublished one when ``preview`` is a valid
    token for exactly that job (recruiter preview, spec 5.3). Apply, upload
    and feed callers never pass ``preview``, so a preview cannot apply.
    Views card: a request carrying a valid preview token must not count."""
    job = await jobs_service.get_published_job(db, company, job_slug)
    if job is not None:
        return job
    if preview is not None:
        previewed = await jobs_service.get_job_by_slug(db, company, job_slug)
        if previewed is not None and read_preview_token(preview) == previewed.id:
            return previewed
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")


def _count_view(
    request: Request, background: BackgroundTasks, db: DbSession, job: Job, preview: str | None
) -> None:
    """Spec 5.5: count the load when the SSR says so, the job is live and no
    preview token was involved. The write happens after the response."""
    if not views_service.wants_view(request) or preview is not None:
        return
    if job.status is not JobStatus.PUBLISHED:
        return
    bind = db.bind
    if bind is None:  # typed as optional upstream; a request session is always bound
        return
    source = views_service.view_source(request.headers.get(views_service.SOURCE_HEADER))
    background.add_task(views_service.record_view_task, bind, job.id, source)


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
async def company_job(
    company: PublicCompany,
    job_slug: str,
    db: DbSession,
    request: Request,
    background: BackgroundTasks,
    preview: str | None = None,
) -> Job:
    job = await _published_job_or_404(db, company, job_slug, preview)
    _count_view(request, background, db, job, preview)
    return job


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
async def single_company_job(
    company: SingleCompany,
    job_slug: str,
    db: DbSession,
    request: Request,
    background: BackgroundTasks,
    preview: str | None = None,
) -> Job:
    job = await _published_job_or_404(db, company, job_slug, preview)
    _count_view(request, background, db, job, preview)
    return job


# Candidate privacy notice (M5.6 G1): per-company variables for the
# frontend-rendered Art. 13 notice; fallbacks applied server-side.
@router.get(
    "/companies/{slug}/privacy",
    response_model=PublicPrivacyNotice,
    dependencies=[rate_limit("public", lambda: settings.rate_limit_public_per_minute)],
)
async def company_privacy_notice(company: PublicCompany) -> PublicPrivacyNotice:
    return company_service.privacy_notice(company)


@router.get(
    "/company/privacy",
    response_model=PublicPrivacyNotice,
    dependencies=[rate_limit("public", lambda: settings.rate_limit_public_per_minute)],
)
async def single_privacy_notice(company: SingleCompany) -> PublicPrivacyNotice:
    return company_service.privacy_notice(company)


async def _jobs_feed(db: DbSession, company: Company, response: Response) -> JobsFeed:
    """Published roles as third-party-friendly JSON (screen 25).

    Meant for company marketing sites: open CORS and a short shared-cache
    TTL (the security middleware's no-store applies to everything else on
    /api/v1 via setdefault, so these explicit headers win).
    """
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
                apply_url=urls.job_url(company, job.slug),
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
    "/challenge",
    dependencies=[rate_limit("public", lambda: settings.rate_limit_public_per_minute)],
)
async def captcha_challenge() -> dict[str, object]:
    """Fresh proof-of-work challenge for the ALTCHA widget (card A5).
    404 while the feature is off, which is how the forms learn whether to
    render the widget at all."""
    if not challenge.active():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Captcha is off")
    return challenge.create()


@router.get(
    "/companies/{slug}/logo",
    dependencies=[rate_limit("public", lambda: settings.rate_limit_public_per_minute)],
)
async def company_logo(company: PublicCompany) -> Response:
    """Serve the branding logo at its mutable path (option B: same-origin,
    no public bucket). Short shared cache: logo_url values stored before
    card A8 point here with a ``?v=`` param. New uploads get the digest
    route below. The CSP neuters scriptable SVGs even when the file is
    opened directly."""
    data, content_type = await _logo_bytes(company)
    return _logo_response(data, content_type, cache_control="public, max-age=3600")


@router.get(
    "/companies/{slug}/logo/{digest}",
    dependencies=[rate_limit("public", lambda: settings.rate_limit_public_per_minute)],
)
async def company_logo_immutable(company: PublicCompany, digest: str) -> Response:
    """Content-addressed logo (card A8): the digest in the path changes
    with every upload, so the answer is immutable for a year and any CDN
    or reverse proxy may cache it. A digest that no longer matches is a
    404 rather than a stale image cached forever."""
    data, content_type = await _logo_bytes(company)
    if digest != company_service.logo_digest(data):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No logo")
    return _logo_response(data, content_type, cache_control="public, max-age=31536000, immutable")


async def _logo_bytes(company: Company) -> tuple[bytes, str]:
    if company.logo_url is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No logo")
    stored = await storage.get_object(storage.build_logo_key(company.id))
    if stored is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No logo")
    return stored


def _logo_response(data: bytes, content_type: str, *, cache_control: str) -> Response:
    return Response(
        content=data,
        media_type=content_type,
        headers={
            "Cache-Control": cache_control,
            "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'",
        },
    )


@router.get(
    "/company/jobs-feed",
    response_model=JobsFeed,
    dependencies=[rate_limit("public", lambda: settings.rate_limit_public_per_minute)],
)
async def single_jobs_feed(company: SingleCompany, db: DbSession, response: Response) -> JobsFeed:
    return await _jobs_feed(db, company, response)


def _upload_ticket(company: Company) -> CvUploadTicket:
    object_key = storage.build_cv_key(company.id)
    upload_url, upload_fields = storage.presign_cv_upload(object_key)
    return CvUploadTicket(
        upload_url=upload_url,
        upload_fields=upload_fields,
        object_key=object_key,
        content_type=storage.CV_CONTENT_TYPE,
        max_size_mb=settings.cv_max_size_mb,
    )


async def _apply(
    db: DbSession,
    company: Company,
    job_slug: str,
    payload: ApplicationSubmit,
) -> ApplicationReceived:
    job = await _published_job_or_404(db, company, job_slug)
    await challenge.require(payload.altcha)  # before quotas: bots must not burn them
    try:
        # emails are counted where they are queued; applications count per attempt
        await quotas.guard(db, company, quotas.EMAILS, consume=False)
        await quotas.guard(db, company, quotas.APPLICATIONS, consume=True)
    except quotas.QuotaExceeded as exc:
        raise _quota_429(exc) from None
    if demo_mode.enabled():
        # nothing the visitor typed is stored; see services/demo_mode.py
        payload = await demo_mode.sanitize(company, payload)
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
        # assessment attached -> the invite (17a) subsumes the generic confirmation
        await outbox_service.queue_email(
            db,
            kind="quiz_invite",
            company_id=company.id,
            application_id=application.id,
            to=payload.email,
            ref=str(application.id),
            candidate_name=payload.name,
            job_title=job.title,
            company_name=company.name,
            brand_primary=(company.theme or {}).get("primary_color"),
            quiz_url=urls.quiz_url(company, quiz_token),
            question_count=len(attempt.question_ids),
            seconds_per_question=quiz_service.seconds_per_question(attempt),
            expires_at=attempt.expires_at,
            controller_name=company_service.controller_name(company),
            privacy_url=urls.privacy_notice_url(company),
        )
    else:
        await outbox_service.queue_email(
            db,
            kind="application_received",
            company_id=company.id,
            application_id=application.id,
            to=payload.email,
            ref=str(application.id),
            candidate_name=payload.name,
            job_title=job.title,
            company_name=company.name,
            privacy_url=urls.privacy_notice_url(company),
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
    demo_mode.forbid_upload()
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
) -> ApplicationReceived:
    return await _apply(db, company, job_slug, payload)


@router.post(
    "/company/jobs/{job_slug}/apply/upload-url",
    response_model=CvUploadTicket,
    dependencies=[rate_limit("upload", lambda: settings.rate_limit_upload_per_minute)],
)
async def single_cv_upload_url(
    company: SingleCompany, job_slug: str, db: DbSession
) -> CvUploadTicket:
    demo_mode.forbid_upload()
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
) -> ApplicationReceived:
    return await _apply(db, company, job_slug, payload)


async def _attempt_or_404(db: DbSession, token: str) -> "QuizAttempt":
    attempt_id = read_quiz_token(token)
    attempt = (
        await quiz_service.get_attempt_by_id(db, attempt_id) if attempt_id is not None else None
    )
    if attempt is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Quiz not found")
    return attempt


async def _progress(db: DbSession, attempt: "QuizAttempt") -> tuple[int, int]:
    """(answered, timed_out) over the resolved questions of an attempt.

    A resolved row without an answer key is a missed deadline; it must not
    read as "answered" on any candidate-facing surface.
    """
    resolved = [a for a in await quiz_service.resolved_answers(db, attempt) if a.answered_at]
    answered = sum(1 for a in resolved if a.answer_key is not None)
    return answered, len(resolved) - answered


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
    answered, timed_out = await _progress(db, attempt)
    return QuizStateOut(
        status=attempt.status.value,
        answered=answered,
        timed_out=timed_out,
        total=len(attempt.question_ids),
        candidate_name=application.candidate.name,
        company_name=company.name,
        job_title=job.title,
        brand_primary=(company.theme or {}).get("primary_color"),
        seconds_per_question=quiz_service.seconds_per_question(attempt),
        expires_at=attempt.expires_at,
        practice_available=practice_available,
        status_token=create_status_token(attempt.application_id),
        privacy_url=urls.privacy_notice_url(company),
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
    answered, timed_out = await _progress(db, attempt)
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
            server_now=datetime.now(UTC),
            # a missed question keeps its slot in the progression
            index=answered + timed_out + 1,
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
    token: str, db: DbSession, payload: ReissueRequest | None = None
) -> dict[str, bool]:
    """Expired-link screen (27c): ask for a fresh assessment link.

    Company setting ``quiz_expired_reissue`` decides: 'auto' re-issues a
    fresh attempt once (email delivery only - the new token is never
    returned to the caller of an old link); 'manual' (default) records
    the request for the team to act on. The lateness stays visible either
    way - the fresh attempt carries reason='expired', the manual request
    lands in the expired attempt's integrity.
    """
    attempt = await _attempt_or_404(db, token)
    await challenge.require(payload.altcha if payload is not None else None)
    now = datetime.now(UTC)
    if attempt.status is AttemptStatus.PENDING and now > attempt.expires_at:
        attempt.status = AttemptStatus.EXPIRED
        await db.commit()
    if attempt.status is AttemptStatus.INVALIDATED:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A new link was already issued - check your inbox",
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
            detail="A new link was already issued - check your inbox",
        )

    mode = (company.settings or {}).get("quiz_expired_reissue", "manual")
    auto_used = any(
        (prior.integrity or {}).get("reissue", {}).get("mode") == "auto"
        for prior in application.quiz_attempts
    )
    if mode == "auto" and not auto_used:
        try:
            await quotas.guard(db, company, quotas.EMAILS, consume=False)
        except quotas.QuotaExceeded as exc:
            raise _quota_429(exc) from None
        fresh = await quiz_service.reissue_attempt(
            db, company, application, job, reason="expired", mode="auto", by_user_id=None
        )
        if fresh is not None:
            await outbox_service.queue_email(
                db,
                kind="quiz_invite",
                company_id=company.id,
                application_id=application.id,
                to=application.candidate.email,
                ref=str(application.id),
                candidate_name=application.candidate.name,
                job_title=job.title,
                company_name=company.name,
                brand_primary=(company.theme or {}).get("primary_color"),
                quiz_url=urls.quiz_url(company, create_quiz_token(fresh.id)),
                question_count=len(fresh.question_ids),
                seconds_per_question=quiz_service.seconds_per_question(fresh),
                expires_at=fresh.expires_at,
                controller_name=company_service.controller_name(company),
                privacy_url=urls.privacy_notice_url(company),
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
    answered, timed_out = await _progress(db, attempt) if attempt is not None else (0, 0)
    quiz = (
        StatusQuizOut(
            status=attempt.status.value,
            answered=answered,
            timed_out=timed_out,
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
        retention_months=company_service.privacy_notice(company).retention_months,
        privacy_url=urls.privacy_notice_url(company),
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
        previous = applications_service.move_stage(
            application, ApplicationStage.WITHDRAWN, reason=rejection_reasons.WITHDREW
        )
        # actor NULL = the candidate; the panel timeline reads "withdrew"
        activity.record(
            db,
            company_id=application.company_id,
            type=activity.STAGE_CHANGED,
            application_id=application.id,
            payload={
                "from": previous.value,
                "to": ApplicationStage.WITHDRAWN.value,
                "reason": rejection_reasons.WITHDREW,
            },
        )
        await db.commit()
    return {"withdrawn": True}


async def _record_privacy_request(db: DbSession, application: Application, *, kind: str) -> None:
    """Notify-only (G0 decision): a Task for the team + an activity entry.

    The task title/note name the candidate on purpose - the task IS the
    request and the admin needs to know who to act for. Repeat clicks
    don't stack open tasks; the activity trail keeps every request."""
    candidate = application.candidate
    title = f"Privacy: {'data' if kind == 'data' else 'deletion'} request - {candidate.name}"
    open_exists = (
        await db.execute(
            select(Task.id)
            .where(
                Task.company_id == application.company_id,
                Task.title == title,
                Task.done_at.is_(None),
            )
            .limit(1)
        )
    ).first()
    if open_exists is None:
        db.add(
            Task(
                company_id=application.company_id,
                created_by=None,
                assignee_user_id=None,
                title=title,
                due_date=date.today() + timedelta(days=14),
                note=(
                    f"{candidate.name} ({candidate.email}) asked via their status page "
                    f"({application.job.title}). GDPR clock: respond within one month."
                ),
            )
        )
    activity.record(
        db,
        company_id=application.company_id,
        type=activity.DATA_REQUESTED if kind == "data" else activity.DELETION_REQUESTED,
        application_id=application.id,
        payload={},
    )
    await db.commit()


@router.post(
    "/applications/{token}/request-data",
    response_model=PrivacyRequestReceipt,
    dependencies=[rate_limit("public", lambda: settings.rate_limit_public_per_minute)],
)
async def request_application_data(token: str, db: DbSession) -> PrivacyRequestReceipt:
    """Art. 15 route for candidates: asks the company, never serves the bundle
    itself - a leaked magic link must not become a full-PII download."""
    application = await _application_by_status_token_or_404(db, token)
    await _record_privacy_request(db, application, kind="data")
    return PrivacyRequestReceipt(status="received")


@router.post(
    "/applications/{token}/request-deletion",
    response_model=PrivacyRequestReceipt,
    dependencies=[rate_limit("public", lambda: settings.rate_limit_public_per_minute)],
)
async def request_application_deletion(token: str, db: DbSession) -> PrivacyRequestReceipt:
    """Art. 17 route for candidates: notify-only, the controller decides
    (retention-for-claims-defense can be a legitimate refusal)."""
    application = await _application_by_status_token_or_404(db, token)
    await _record_privacy_request(db, application, kind="deletion")
    return PrivacyRequestReceipt(status="received")


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


async def _interview_by_token_or_404(db: DbSession, token: str) -> Interview:
    interview_id = read_interview_token(token)
    interview = (
        await interviews_service.get_by_id_public(db, interview_id)
        if interview_id is not None
        else None
    )
    if interview is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Interview not found")
    return interview


async def _interview_public(
    db: DbSession, interview: Interview, company: Company
) -> InterviewPublicOut:
    candidate = interview.application.candidate
    display = interview.interviewer.display_label  # display name, else email local part
    booked = interview.status is InterviewStatus.BOOKED
    return InterviewPublicOut(
        company_name=company.name,
        brand_primary=(company.theme or {}).get("primary_color"),
        logo_url=company.logo_url,
        job_title=interview.application.job.title,
        candidate_first_name=(candidate.name or "there").split()[0],
        title=interview.title,
        description=interview.description,
        duration_minutes=interview.duration_minutes,
        timezone=interview.timezone,
        status=interview.status.value,
        interviewer_display=display,
        available_slots=await interviews_service.live_slots(db, interview),
        scheduled_start=interview.scheduled_start,
        meet_url=interview.meet_url if booked else None,
    )


async def _interview_company(db: DbSession, interview: Interview) -> Company:
    return (
        await db.execute(select(Company).where(Company.id == interview.company_id))
    ).scalar_one()


@router.get(
    "/interviews/{token}",
    response_model=InterviewPublicOut,
    dependencies=[rate_limit("public", lambda: settings.rate_limit_public_per_minute)],
)
async def interview_context(token: str, db: DbSession) -> InterviewPublicOut:
    """Candidate booking page (screen 23) behind its signed magic-link token."""
    interview = await _interview_by_token_or_404(db, token)
    return await _interview_public(db, interview, await _interview_company(db, interview))


def _scheduling_unavailable() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail="Scheduling is temporarily unavailable - please try again later",
    )


@router.post(
    "/interviews/{token}/book",
    response_model=InterviewPublicOut,
    dependencies=[rate_limit("public", lambda: settings.rate_limit_public_per_minute)],
)
async def interview_book(
    token: str, payload: InterviewSlotBody, db: DbSession
) -> InterviewPublicOut:
    interview = await _interview_by_token_or_404(db, token)
    if interview.status is InterviewStatus.CANCELLED:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="This interview was cancelled"
        )
    try:
        interview = await interviews_service.book(db, interview, start=payload.start)
    except interviews_service.AlreadyBookedError:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="already-booked") from None
    except interviews_service.SlotUnavailableError:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="slot-taken") from None
    except interviews_service.LockBusyError:
        raise _scheduling_unavailable() from None
    except google_calendar.GoogleCalendarError:
        raise _scheduling_unavailable() from None
    return await _interview_public(db, interview, await _interview_company(db, interview))


@router.post(
    "/interviews/{token}/reschedule",
    response_model=InterviewPublicOut,
    dependencies=[rate_limit("public", lambda: settings.rate_limit_public_per_minute)],
)
async def interview_reschedule(
    token: str, payload: InterviewSlotBody, db: DbSession
) -> InterviewPublicOut:
    interview = await _interview_by_token_or_404(db, token)
    try:
        interview = await interviews_service.reschedule(db, interview, start=payload.start)
    except interviews_service.NotBookedError:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="not-booked") from None
    except interviews_service.SlotUnavailableError:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="slot-taken") from None
    except interviews_service.LockBusyError:
        raise _scheduling_unavailable() from None
    except google_calendar.GoogleCalendarError:
        raise _scheduling_unavailable() from None
    return await _interview_public(db, interview, await _interview_company(db, interview))


@router.post(
    "/interviews/{token}/cancel",
    response_model=InterviewPublicOut,
    dependencies=[rate_limit("public", lambda: settings.rate_limit_public_per_minute)],
)
async def interview_cancel(token: str, db: DbSession) -> InterviewPublicOut:
    interview = await _interview_by_token_or_404(db, token)
    try:
        interview = await interviews_service.candidate_cancel(db, interview)
    except interviews_service.LockBusyError:
        raise _scheduling_unavailable() from None
    except google_calendar.GoogleCalendarError:
        raise _scheduling_unavailable() from None
    return await _interview_public(db, interview, await _interview_company(db, interview))
