import math
import uuid
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import select

from app.api.deps import AdminUser, CurrentCompany, CurrentUser, DbSession
from app.core.config import settings
from app.core.security import create_interview_token, create_quiz_token, create_status_token
from app.models import Application, ApplicationNote, ApplicationStage, EmailOutbox, User, UserRole
from app.models.quiz import AttemptStatus, QuizAttempt
from app.schemas.applications import (
    ApplicationOut,
    ApplicationPage,
    BulkRejectIn,
    BulkRejectOut,
    CandidateEmailUpdate,
    CvDownload,
    EmailDeliveryOut,
    EraseCandidateOut,
    NoteCreate,
    NoteOut,
    QuizAnswerReview,
    QuizResultOut,
    ReviewIntegrityEvent,
    StageUpdate,
)
from app.schemas.dsar import DsarBundle
from app.schemas.interviews import InterviewCreate, InterviewOut, SlotPreviewOut, SlotPreviewRequest
from app.services import activity, google_calendar, storage
from app.services import applications as applications_service
from app.services import company as company_service
from app.services import dsar as dsar_service
from app.services import erasure as erasure_service
from app.services import interviews as interviews_service
from app.services import outbox as outbox_service
from app.services import quiz as quiz_service

router = APIRouter(prefix="/applications", tags=["applications"])


async def _get_or_404(
    db: DbSession, company: CurrentCompany, application_id: uuid.UUID
) -> Application:
    application = await applications_service.get_application(db, company, application_id)
    if application is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Application not found")
    return application


@router.get("", response_model=ApplicationPage)
async def list_applications(
    db: DbSession,
    company: CurrentCompany,
    job_id: uuid.UUID | None = None,
    stage: ApplicationStage | None = None,
    limit: int = Query(default=100, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> ApplicationPage:
    items, total = await applications_service.list_applications(
        db, company, job_id=job_id, stage=stage, limit=limit, offset=offset
    )
    return ApplicationPage(
        items=[ApplicationOut.model_validate(item) for item in items],
        total=total,
        stage_counts=await applications_service.count_by_stage(db, company, job_id=job_id),
    )


@router.post("/bulk-reject", response_model=BulkRejectOut)
async def bulk_reject_applications(
    payload: BulkRejectIn,
    db: DbSession,
    company: CurrentCompany,
    user: CurrentUser,
) -> BulkRejectOut:
    # literal path — must stay declared before /{application_id} routes,
    # which would otherwise shadow it (FastAPI matches in declaration order)
    rejected = await applications_service.bulk_reject(
        db, company, payload.application_ids, actor_user_id=user.id
    )
    if payload.notify_candidates:
        for application in rejected:
            await _queue_rejection_email(db, company, application)
    return BulkRejectOut(
        rejected=len(rejected), skipped=len(payload.application_ids) - len(rejected)
    )


@router.get("/{application_id}", response_model=ApplicationOut)
async def get_application(
    application_id: uuid.UUID, db: DbSession, company: CurrentCompany
) -> Application:
    return await _get_or_404(db, company, application_id)


@router.patch("/{application_id}/stage", response_model=ApplicationOut)
async def set_stage(
    application_id: uuid.UUID,
    payload: StageUpdate,
    db: DbSession,
    company: CurrentCompany,
    user: CurrentUser,
) -> Application:
    application = await _get_or_404(db, company, application_id)
    updated = await applications_service.set_stage(
        db, application, payload.stage, actor_user_id=user.id
    )
    if payload.notify_candidate:
        await _queue_stage_email(db, company, application, payload.stage)
    return updated


@router.post("/{application_id}/erase-candidate", response_model=EraseCandidateOut)
async def erase_candidate(
    application_id: uuid.UUID,
    db: DbSession,
    company: CurrentCompany,
    admin: AdminUser,
) -> EraseCandidateOut:
    """Art. 17: erases the whole CANDIDATE — every application they hold with
    this company, their CVs in storage and (best-effort) their calendar
    events — not just the application the panel happened to be showing."""
    application = await _get_or_404(db, company, application_id)
    summary = await erasure_service.erase_candidate(
        db, company, application.candidate_id, actor_user_id=admin.id
    )
    assert summary is not None  # the application existed, so its candidate does
    return EraseCandidateOut(
        applications=summary.applications,
        google_event_failures=summary.google_event_failures,
    )


@router.get("/{application_id}/dsar-export", response_model=DsarBundle)
async def dsar_export(
    application_id: uuid.UUID,
    db: DbSession,
    company: CurrentCompany,
    _admin: AdminUser,
) -> DsarBundle:
    """Art. 15/20: the full bundle for the CANDIDATE behind this application —
    all their applications with this company, admin-mediated by design."""
    application = await _get_or_404(db, company, application_id)
    bundle = await dsar_service.export_candidate(db, company, application.candidate_id)
    assert bundle is not None  # the application existed, so its candidate does
    return bundle


@router.patch("/{application_id}/candidate-email", response_model=ApplicationOut)
async def update_candidate_email(
    application_id: uuid.UUID,
    payload: CandidateEmailUpdate,
    db: DbSession,
    company: CurrentCompany,
    admin: AdminUser,
) -> Application:
    """Art. 16: the email address is the delivery channel for every candidate
    link and has no self-service correction path."""
    application = await _get_or_404(db, company, application_id)
    try:
        return await applications_service.update_candidate_email(
            db, company, application, payload.email, actor_user_id=admin.id
        )
    except applications_service.EmailTakenByOtherCandidateError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Another candidate already uses this email",
        ) from None


@router.post("/{application_id}/remind", response_model=dict[str, bool])
async def remind_candidate(
    application_id: uuid.UUID,
    db: DbSession,
    company: CurrentCompany,
) -> dict[str, bool]:
    """Manually resend the assessment link (17b) while the attempt is untouched."""
    application = await _get_or_404(db, company, application_id)
    attempt = application.quiz_attempt
    now = datetime.now(UTC)
    if attempt is None or attempt.status is not AttemptStatus.PENDING or attempt.expires_at <= now:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="No pending assessment to remind about",
        )
    days_left = max(0, math.ceil((attempt.expires_at - now).total_seconds() / 86400))
    await outbox_service.queue_email(
        db,
        kind="quiz_reminder",
        company_id=company.id,
        application_id=application.id,
        to=application.candidate.email,
        ref=str(application.id),
        candidate_name=application.candidate.name,
        job_title=application.job.title,
        company_name=company.name,
        brand_primary=(company.theme or {}).get("primary_color"),
        quiz_url=f"{settings.public_base_url.rstrip('/')}/quiz/{create_quiz_token(attempt.id)}",
        expires_at=attempt.expires_at,
        days_left=days_left,
        controller_name=company_service.controller_name(company),
        privacy_url=company_service.privacy_notice_url(company),
    )
    return {"sent": True}


@router.get("/{application_id}/notes", response_model=list[NoteOut])
async def list_notes(
    application_id: uuid.UUID, db: DbSession, company: CurrentCompany
) -> list[ApplicationNote]:
    await _get_or_404(db, company, application_id)
    return list(
        (
            await db.execute(
                select(ApplicationNote)
                .where(
                    ApplicationNote.company_id == company.id,
                    ApplicationNote.application_id == application_id,
                )
                .order_by(ApplicationNote.created_at, ApplicationNote.id)
            )
        )
        .scalars()
        .all()
    )


@router.post("/{application_id}/notes", response_model=NoteOut, status_code=status.HTTP_201_CREATED)
async def add_note(
    application_id: uuid.UUID,
    payload: NoteCreate,
    db: DbSession,
    company: CurrentCompany,
    user: CurrentUser,
) -> ApplicationNote:
    await _get_or_404(db, company, application_id)
    note = ApplicationNote(
        company_id=company.id,
        application_id=application_id,
        author_user_id=user.id,
        body=payload.body,
    )
    db.add(note)
    activity.record(
        db,
        company_id=company.id,
        type=activity.NOTE_ADDED,
        actor_user_id=user.id,
        application_id=application_id,
    )
    await db.commit()
    await db.refresh(note)
    return note


@router.delete("/{application_id}/notes/{note_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_note(
    application_id: uuid.UUID,
    note_id: uuid.UUID,
    db: DbSession,
    company: CurrentCompany,
    user: CurrentUser,
) -> None:
    note = (
        await db.execute(
            select(ApplicationNote).where(
                ApplicationNote.id == note_id,
                ApplicationNote.company_id == company.id,
                ApplicationNote.application_id == application_id,
            )
        )
    ).scalar_one_or_none()
    if note is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Note not found")
    if note.author_user_id != user.id and user.role is not UserRole.ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the author or an admin can delete a note",
        )
    await db.delete(note)
    await db.commit()


@router.post("/{application_id}/quiz/reissue", response_model=QuizResultOut)
async def reissue_quiz(
    application_id: uuid.UUID,
    db: DbSession,
    company: CurrentCompany,
    user: CurrentUser,
) -> QuizAttempt:
    """Invalidate & re-invite to a fresh quiz (screen 24; also the expired-link
    path). The superseded attempt stays as history; the candidate gets a new
    link with a fresh 24h window."""
    application = await _get_or_404(db, company, application_id)
    latest = application.quiz_attempt
    if latest is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="No assessment to re-issue"
        )
    reason = "expired" if latest.status is AttemptStatus.EXPIRED else "integrity"
    attempt = await quiz_service.reissue_attempt(
        db,
        company,
        application,
        application.job,
        reason=reason,
        mode="manual",
        by_user_id=user.id,
    )
    if attempt is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This job's assessment is disabled or has no questions to serve",
        )
    await outbox_service.queue_email(
        db,
        kind="quiz_invite",
        company_id=company.id,
        application_id=application.id,
        to=application.candidate.email,
        ref=str(application.id),
        candidate_name=application.candidate.name,
        job_title=application.job.title,
        company_name=company.name,
        brand_primary=(company.theme or {}).get("primary_color"),
        quiz_url=f"{settings.public_base_url.rstrip('/')}/quiz/{create_quiz_token(attempt.id)}",
        question_count=len(attempt.question_ids),
        seconds_per_question=attempt.time_limit_seconds,
        expires_at=attempt.expires_at,
        controller_name=company_service.controller_name(company),
        privacy_url=company_service.privacy_notice_url(company),
    )
    return attempt


@router.post("/{application_id}/quiz/dismiss-flags", response_model=QuizResultOut)
async def dismiss_quiz_flags(
    application_id: uuid.UUID,
    db: DbSession,
    company: CurrentCompany,
    user: CurrentUser,
) -> QuizAttempt:
    """Screen 24 'looks fine': record who reviewed the flags and when."""
    application = await _get_or_404(db, company, application_id)
    attempt = application.quiz_attempt
    if attempt is None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="No assessment to review")
    return await quiz_service.dismiss_flags(db, attempt, by_user_id=user.id)


async def _interviewer_or_404(
    db: DbSession, company: CurrentCompany, interviewer_user_id: uuid.UUID
) -> User:
    interviewer = (
        await db.execute(
            select(User).where(
                User.company_id == company.id,
                User.id == interviewer_user_id,
                User.is_active,
            )
        )
    ).scalar_one_or_none()
    if interviewer is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Interviewer not found")
    return interviewer


@router.post("/{application_id}/interview/slot-preview", response_model=SlotPreviewOut)
async def interview_slot_preview(
    application_id: uuid.UUID,
    payload: SlotPreviewRequest,
    db: DbSession,
    company: CurrentCompany,
) -> SlotPreviewOut:
    """Availability summary + open slot count for the modal — nothing is persisted."""
    await _get_or_404(db, company, application_id)
    interviewer = await _interviewer_or_404(db, company, payload.interviewer_user_id)
    saved_tz, windows = interviews_service.effective_availability(interviewer)
    try:
        slots = await interviews_service.generate_slots(
            db,
            interviewer,
            duration_minutes=payload.duration_minutes,
            timezone=payload.timezone,
        )
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Unknown timezone"
        ) from None
    except google_calendar.NeedsReconnectError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Interviewer has not connected Google Calendar",
        ) from None
    # Same resolution generate_slots uses: the interviewer's saved zone wins,
    # otherwise the request's fallback — recruiters need to know whose clock
    # the bare hours are in.
    zone = saved_tz or payload.timezone
    return SlotPreviewOut(
        schedule_summary=f"{interviews_service.summarize_availability(windows)} ({zone})",
        open_slot_count=len(slots),
    )


@router.post(
    "/{application_id}/interview",
    response_model=InterviewOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_interview(
    application_id: uuid.UUID,
    payload: InterviewCreate,
    db: DbSession,
    company: CurrentCompany,
    user: CurrentUser,
) -> object:
    application = await _get_or_404(db, company, application_id)
    interviewer = await _interviewer_or_404(db, company, payload.interviewer_user_id)
    if await google_calendar.get_credential(db, interviewer) is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Interviewer has not connected Google Calendar",
        )
    try:
        ZoneInfo(payload.timezone)
    except Exception:  # noqa: BLE001 - any zoneinfo failure means a bad zone
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Unknown timezone"
        ) from None
    try:
        interview = await interviews_service.create_interview(
            db,
            company,
            application,
            interviewer=interviewer,
            title=payload.title,
            description=payload.description,
            duration_minutes=payload.duration_minutes,
            timezone=payload.timezone,
            actor_user_id=user.id,
        )
    except interviews_service.InterviewExistsError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This application already has an interview in progress",
        ) from None
    booking_url = (
        f"{settings.public_base_url.rstrip('/')}/interview/{create_interview_token(interview.id)}"
    )
    await outbox_service.queue_email(
        db,
        kind="interview_invite",
        company_id=company.id,
        application_id=application.id,
        to=application.candidate.email,
        ref=str(application.id),
        candidate_name=application.candidate.name,
        job_title=application.job.title,
        company_name=company.name,
        duration_minutes=interview.duration_minutes,
        booking_url=booking_url,
        brand_primary=(company.theme or {}).get("primary_color"),
        controller_name=company_service.controller_name(company),
        privacy_url=company_service.privacy_notice_url(company),
    )
    return interview


@router.get("/{application_id}/interview", response_model=InterviewOut | None)
async def get_interview(
    application_id: uuid.UUID, db: DbSession, company: CurrentCompany
) -> object:
    await _get_or_404(db, company, application_id)
    return await interviews_service.get_for_application(db, company, application_id)


@router.post("/{application_id}/interview/cancel", response_model=InterviewOut)
async def cancel_interview(
    application_id: uuid.UUID,
    db: DbSession,
    company: CurrentCompany,
    user: CurrentUser,
) -> object:
    application = await _get_or_404(db, company, application_id)
    interview = await interviews_service.get_for_application(db, company, application_id)
    if interview is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="No active interview to cancel"
        )
    await interviews_service.cancel_interview(
        db, interview, interviewer=interview.interviewer, actor_user_id=user.id
    )
    await outbox_service.queue_email(
        db,
        kind="interview_cancelled",
        company_id=company.id,
        application_id=application.id,
        to=application.candidate.email,
        ref=str(application.id),
        candidate_name=application.candidate.name,
        job_title=application.job.title,
        company_name=company.name,
        controller_name=company_service.controller_name(company),
        privacy_url=company_service.privacy_notice_url(company),
    )
    return interview


async def _queue_rejection_email(
    db: DbSession, company: CurrentCompany, application: Application
) -> None:
    """22b: shared by the single-stage PATCH and bulk-reject so they can't drift."""
    candidate = application.candidate
    job = application.job
    base = settings.public_base_url.rstrip("/")
    careers_url = base if settings.mode == "single" else f"{base}/c/{company.slug}"
    attempt = application.quiz_attempt
    await outbox_service.queue_email(
        db,
        kind="rejection",
        company_id=company.id,
        application_id=application.id,
        to=candidate.email,
        ref=str(application.id),
        candidate_name=candidate.name,
        job_title=job.title,
        company_name=company.name,
        careers_url=careers_url,
        completed_assessment=attempt is not None and attempt.completed_at is not None,
        controller_name=company_service.controller_name(company),
        privacy_url=company_service.privacy_notice_url(company),
    )


async def _queue_stage_email(
    db: DbSession,
    company: CurrentCompany,
    application: Application,
    stage: ApplicationStage,
) -> None:
    """Queue 22a/22b for stages with a template; other stages are a no-op."""
    if stage is ApplicationStage.INTERVIEW:
        candidate = application.candidate
        job = application.job
        base = settings.public_base_url.rstrip("/")
        await outbox_service.queue_email(
            db,
            kind="stage_advance",
            company_id=company.id,
            application_id=application.id,
            to=candidate.email,
            ref=str(application.id),
            candidate_name=candidate.name,
            job_title=job.title,
            company_name=company.name,
            brand_primary=(company.theme or {}).get("primary_color"),
            status_url=f"{base}/application/{create_status_token(application.id)}",
            controller_name=company_service.controller_name(company),
            privacy_url=company_service.privacy_notice_url(company),
        )
    elif stage is ApplicationStage.REJECTED:
        await _queue_rejection_email(db, company, application)


@router.get("/{application_id}/cv-url", response_model=CvDownload)
async def cv_download_url(
    application_id: uuid.UUID, db: DbSession, company: CurrentCompany
) -> CvDownload:
    application = await _get_or_404(db, company, application_id)
    return CvDownload(
        download_url=storage.presign_cv_download(application.cv_object_key, application.cv_filename)
    )


@router.get("/{application_id}/emails", response_model=list[EmailDeliveryOut])
async def email_deliveries(
    application_id: uuid.UUID, db: DbSession, company: CurrentCompany
) -> list[EmailOutbox]:
    """Delivery trail for the applicant panel (M5.7 H4): whether the mails
    this application depends on actually went out, newest first."""
    await _get_or_404(db, company, application_id)
    return list(
        (
            await db.execute(
                select(EmailOutbox)
                .where(
                    EmailOutbox.company_id == company.id,
                    EmailOutbox.application_id == application_id,
                )
                .order_by(EmailOutbox.created_at.desc())
            )
        )
        .scalars()
        .all()
    )


@router.get("/{application_id}/quiz-answers", response_model=list[QuizAnswerReview])
async def quiz_answers(
    application_id: uuid.UUID, db: DbSession, company: CurrentCompany
) -> list[QuizAnswerReview]:
    application = await _get_or_404(db, company, application_id)
    attempt = await quiz_service.get_attempt_by_application(db, application.id)
    if attempt is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="No quiz for this application"
        )
    events = attempt.integrity.get("events", [])
    reviews: list[QuizAnswerReview] = []
    for answer, question in await quiz_service.review_answers(db, attempt):
        response_ms: int | None = None
        if answer.answer_key is not None and answer.answered_at is not None:
            response_ms = int((answer.answered_at - answer.served_at).total_seconds() * 1000)
        question_events = [
            ReviewIntegrityEvent(type=str(e.get("type")), duration_ms=e.get("duration_ms"))
            for e in events
            if e.get("question_id") == question.id
        ]
        reviews.append(
            QuizAnswerReview(
                question_id=question.id,
                prompt_md=question.prompt_md,
                options=question.options,
                correct_key=question.correct_key,
                explanation_md=question.explanation_md,
                tags=question.tags,
                answer_key=answer.answer_key,
                is_correct=answer.is_correct,
                response_ms=response_ms,
                integrity_events=question_events,
            )
        )
    return reviews
