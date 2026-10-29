import csv
import io
import math
import uuid
from datetime import UTC, datetime
from typing import Literal
from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException, Query, Request, Response, status
from fastapi.responses import JSONResponse
from sqlalchemy import select

from app.api.deps import (
    AdminUser,
    ApiCompany,
    CurrentCompany,
    CurrentUser,
    DbSession,
    ReadActor,
    WriteActor,
    get_current_user,
)
from app.core import urls
from app.core.security import create_interview_token, create_quiz_token, create_status_token
from app.models import (
    AccessLog,
    Application,
    ApplicationNote,
    ApplicationStage,
    Company,
    EmailOutbox,
    User,
    UserRole,
)
from app.models.quiz import AttemptStatus, QuizAttempt
from app.schemas.applications import (
    AccessEntryOut,
    ApplicationOut,
    ApplicationPage,
    BulkRejectIn,
    BulkRejectOut,
    BulkStageIn,
    BulkStageOut,
    CandidateEmailUpdate,
    CvDownload,
    EmailDeliveryOut,
    EraseCandidateOut,
    ExtraTimeIn,
    NoteCreate,
    NoteOut,
    QuizAnswerReview,
    QuizResultOut,
    ReviewIntegrityEvent,
    StageUpdate,
    TimelineEventOut,
)
from app.schemas.dsar import DsarBundle
from app.schemas.interviews import InterviewCreate, InterviewOut, SlotPreviewOut, SlotPreviewRequest
from app.services import access_log, activity, google_calendar, storage
from app.services import applications as applications_service
from app.services import company as company_service
from app.services import dsar as dsar_service
from app.services import erasure as erasure_service
from app.services import interviews as interviews_service
from app.services import outbox as outbox_service
from app.services import quiz as quiz_service
from app.services import timeline as timeline_service

router = APIRouter(prefix="/applications", tags=["applications"])


async def _session_user_or_none(request: Request, db: DbSession) -> User | None:
    """Export is open to read keys too; a session caller still gets named
    in the activity entry (admin check happens in get_api_company's
    session branch via the company dependency, members included)."""
    if request.headers.get("authorization"):
        return None
    return await get_current_user(request, db)


async def _get_or_404(
    db: DbSession, company: CurrentCompany, application_id: uuid.UUID
) -> Application:
    application = await applications_service.get_application(db, company, application_id)
    if application is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Application not found")
    return application


def _list_filters(
    *,
    job_id: uuid.UUID | None,
    stage: ApplicationStage | None,
    q: str | None,
    score_min: int | None,
    quiz: applications_service.QuizState | None,
    source: str | None,
    flagged: bool | None,
    since_days: int | None,
    ids: tuple[uuid.UUID, ...] = (),
) -> applications_service.ListFilters:
    return applications_service.ListFilters(
        job_id=job_id,
        stage=stage,
        q=(q or "").strip() or None,
        score_min=score_min,
        quiz=quiz,
        source=source,
        flagged=flagged,
        since_days=since_days,
        ids=ids,
    )


def _parse_ids(raw: str | None) -> tuple[uuid.UUID, ...]:
    """`ids=a,b,c` on the export: the bulk bar's selection, same cap as
    bulk reject."""
    if raw is None or raw.strip() == "":
        return ()
    parts = [part.strip() for part in raw.split(",") if part.strip()]
    if len(parts) > applications_service.EXPORT_IDS_MAX:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Up to {applications_service.EXPORT_IDS_MAX} ids per export",
        )
    try:
        return tuple(uuid.UUID(part) for part in parts)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="ids must be UUIDs"
        ) from exc


@router.get("", response_model=ApplicationPage)
async def list_applications(
    db: DbSession,
    company: ApiCompany,
    job_id: uuid.UUID | None = None,
    stage: ApplicationStage | None = None,
    q: str | None = Query(default=None, max_length=applications_service.SEARCH_MAX_LENGTH),
    score_min: int | None = Query(default=None, ge=0, le=100),
    quiz: applications_service.QuizState | None = None,
    source: str | None = Query(default=None, max_length=100),
    flagged: bool | None = None,
    since_days: int | None = Query(default=None, ge=1, le=365),
    sort: applications_service.SortKey = "applied_desc",
    limit: int = Query(default=100, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> ApplicationPage:
    filters = _list_filters(
        job_id=job_id,
        stage=stage,
        q=q,
        score_min=score_min,
        quiz=quiz,
        source=source,
        flagged=flagged,
        since_days=since_days,
    )
    items, total = await applications_service.list_applications(
        db, company, filters=filters, sort=sort, limit=limit, offset=offset
    )
    return ApplicationPage(
        items=[ApplicationOut.model_validate(item) for item in items],
        total=total,
        stage_counts=await applications_service.count_by_stage(db, company, filters=filters),
        sources=await applications_service.list_sources(db, company),
    )


@router.get("/export")
async def export_applications(
    db: DbSession,
    company: ApiCompany,
    request: Request,
    format: Literal["csv", "json"] = "csv",
    job_id: uuid.UUID | None = None,
    stage: ApplicationStage | None = None,
    q: str | None = Query(default=None, max_length=applications_service.SEARCH_MAX_LENGTH),
    score_min: int | None = Query(default=None, ge=0, le=100),
    quiz: applications_service.QuizState | None = None,
    source: str | None = Query(default=None, max_length=100),
    flagged: bool | None = None,
    since_days: int | None = Query(default=None, ge=1, le=365),
    ids: str | None = None,
) -> Response:
    """The current filter as a file (card D9): flat rows, no internal ids,
    quiz columns at summary level. Admin only; one activity entry per
    export names who pulled how many rows. Takes every list filter plus
    `ids` (the bulk bar's selection) so the file is always the rows on
    screen. Declared before the /{application_id} routes so "export" is
    never parsed as an id."""
    filters = _list_filters(
        job_id=job_id,
        stage=stage,
        q=q,
        score_min=score_min,
        quiz=quiz,
        source=source,
        flagged=flagged,
        since_days=since_days,
        ids=_parse_ids(ids),
    )
    rows = await applications_service.export_applications(db, company, filters=filters)
    actor = await _session_user_or_none(request, db)
    activity.record(
        db,
        company_id=company.id,
        type=activity.APPLICATIONS_EXPORTED,
        actor_user_id=actor.id if actor is not None else None,
        payload={
            "format": format,
            "rows": len(rows),
            "stage": stage.value if stage is not None else None,
            "job_id": str(job_id) if job_id is not None else None,
            "filtered": any(
                value is not None
                for value in (filters.q, score_min, quiz, source, flagged, since_days)
            )
            or bool(filters.ids),
        },
    )
    await db.commit()
    stamp = datetime.now(UTC).date().isoformat()
    disposition = f'attachment; filename="applicants-{company.slug}-{stamp}.{format}"'
    if format == "json":
        return JSONResponse(rows, headers={"Content-Disposition": disposition})
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=applications_service.EXPORT_COLUMNS)
    writer.writeheader()
    writer.writerows(rows)
    return Response(
        buffer.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": disposition},
    )


@router.post("/bulk-reject", response_model=BulkRejectOut)
async def bulk_reject_applications(
    payload: BulkRejectIn,
    db: DbSession,
    company: CurrentCompany,
    user: CurrentUser,
) -> BulkRejectOut:
    # literal path - must stay declared before /{application_id} routes,
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


@router.post("/bulk-stage", response_model=BulkStageOut)
async def bulk_stage_applications(
    payload: BulkStageIn,
    db: DbSession,
    company: CurrentCompany,
    user: CurrentUser,
) -> BulkStageOut:
    # literal path, declared before /{application_id} like bulk-reject
    updated = await applications_service.bulk_set_stage(
        db, company, payload.application_ids, payload.stage, actor_user_id=user.id
    )
    if payload.notify_candidates:
        for application in updated:
            await _queue_stage_email(db, company, application, payload.stage)
    return BulkStageOut(updated=len(updated), skipped=len(payload.application_ids) - len(updated))


@router.get("/{application_id}", response_model=ApplicationOut)
async def get_application(
    application_id: uuid.UUID, db: DbSession, reader: ReadActor
) -> Application:
    application = await _get_or_404(db, reader.company, application_id)
    await access_log.record(
        db,
        company=reader.company,
        application_id=application.id,
        action=access_log.VIEW,
        user=reader.user,
        api_key=reader.api_key,
    )
    return application


@router.get("/{application_id}/access-log", response_model=list[AccessEntryOut])
async def application_access_log(
    application_id: uuid.UUID,
    db: DbSession,
    company: CurrentCompany,
    _admin: AdminUser,
) -> list[AccessLog]:
    """Who looked at this candidate, newest first (admins only). Reading
    the trail is not itself a read of the candidate."""
    application = await _get_or_404(db, company, application_id)
    return await access_log.list_for_application(db, company, application.id)


@router.get("/{application_id}/timeline", response_model=list[TimelineEventOut])
async def application_timeline(
    application_id: uuid.UUID, db: DbSession, company: CurrentCompany
) -> list[TimelineEventOut]:
    """What happened to this application, newest first: stage moves with
    the actor, emails with delivery state, quiz milestones, notes,
    interviews. Reading the trail is not itself a read of the candidate,
    so no access-log row."""
    application = await _get_or_404(db, company, application_id)
    return [
        TimelineEventOut.model_validate(event)
        for event in await timeline_service.list_events(db, company, application)
    ]


@router.patch("/{application_id}/stage", response_model=ApplicationOut)
async def set_stage(
    application_id: uuid.UUID,
    payload: StageUpdate,
    db: DbSession,
    actor: WriteActor,
) -> Application:
    company = actor.company
    application = await _get_or_404(db, company, application_id)
    # bulk-reject silently skips already-rejected rows; the single route must
    # not re-send the stage email either when nothing actually changed
    stage_changed = application.stage is not payload.stage
    updated = await applications_service.set_stage(
        db,
        application,
        payload.stage,
        actor_user_id=actor.user.id if actor.user is not None else None,
    )
    if payload.notify_candidate and stage_changed:
        await _queue_stage_email(db, company, application, payload.stage)
    return updated


@router.post("/{application_id}/erase-candidate", response_model=EraseCandidateOut)
async def erase_candidate(
    application_id: uuid.UUID,
    db: DbSession,
    company: CurrentCompany,
    admin: AdminUser,
) -> EraseCandidateOut:
    """Art. 17: erases the whole CANDIDATE - every application they hold with
    this company, their CVs in storage and (best-effort) their calendar
    events - not just the application the panel happened to be showing."""
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
    admin: AdminUser,
) -> DsarBundle:
    """Art. 15/20: the full bundle for the CANDIDATE behind this application -
    all their applications with this company, admin-mediated by design."""
    application = await _get_or_404(db, company, application_id)
    await access_log.record(
        db,
        company=company,
        application_id=application.id,
        action=access_log.DSAR_EXPORT,
        user=admin,
    )
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
        quiz_url=urls.quiz_url(company, create_quiz_token(attempt.id)),
        expires_at=attempt.expires_at,
        days_left=days_left,
        controller_name=company_service.controller_name(company),
        privacy_url=urls.privacy_notice_url(company),
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
    await _queue_quiz_invite(db, company, application, attempt)
    return attempt


async def _queue_quiz_invite(
    db: DbSession, company: Company, application: Application, attempt: QuizAttempt
) -> None:
    """Branded quiz invite (17a) for the attempt's current link and timing."""
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
        quiz_url=urls.quiz_url(company, create_quiz_token(attempt.id)),
        question_count=len(attempt.question_ids),
        seconds_per_question=quiz_service.seconds_per_question(attempt),
        expires_at=attempt.expires_at,
        controller_name=company_service.controller_name(company),
        privacy_url=urls.privacy_notice_url(company),
    )


@router.post("/{application_id}/quiz/extra-time", response_model=QuizResultOut)
async def grant_extra_time(
    application_id: uuid.UUID,
    payload: ExtraTimeIn,
    db: DbSession,
    company: CurrentCompany,
    admin: AdminUser,
) -> QuizAttempt:
    """Extra-time accommodation (1.5x or 2x per question; 1 removes it).
    A pending attempt keeps its questions and link and gets the invite
    again with the new timing; a started, finished or expired one is
    re-issued fresh with the multiplier. Recorded in the attempt's
    integrity data; scoring is untouched."""
    application = await _get_or_404(db, company, application_id)
    if application.quiz_attempt is None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="No assessment to adjust")
    granted = await quiz_service.grant_extra_time(
        db,
        company,
        application,
        application.job,
        multiplier=payload.time_multiplier,
        by_user_id=admin.id,
    )
    if granted is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This job's assessment is disabled or has no questions to serve",
        )
    attempt, _reissued = granted
    await _queue_quiz_invite(db, company, application, attempt)
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
    """Availability summary + open slot count for the modal - nothing is persisted."""
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
    # otherwise the request's fallback - recruiters need to know whose clock
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
    booking_url = urls.interview_url(company, create_interview_token(interview.id))
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
        privacy_url=urls.privacy_notice_url(company),
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
    try:
        await interviews_service.cancel_interview(
            db, interview, interviewer=interview.interviewer, actor_user_id=user.id
        )
    except interviews_service.LockBusyError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Scheduling is busy - try again in a moment",
        ) from None
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
        privacy_url=urls.privacy_notice_url(company),
    )
    return interview


async def _queue_rejection_email(
    db: DbSession, company: CurrentCompany, application: Application
) -> None:
    """22b: shared by the single-stage PATCH and bulk-reject so they can't drift."""
    candidate = application.candidate
    job = application.job
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
        careers_url=urls.careers_url(company),
        completed_assessment=attempt is not None and attempt.completed_at is not None,
        controller_name=company_service.controller_name(company),
        privacy_url=urls.privacy_notice_url(company),
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
            status_url=urls.status_url(company, create_status_token(application.id)),
            controller_name=company_service.controller_name(company),
            privacy_url=urls.privacy_notice_url(company),
        )
    elif stage is ApplicationStage.REJECTED:
        await _queue_rejection_email(db, company, application)


@router.get("/{application_id}/cv-url", response_model=CvDownload)
async def cv_download_url(
    application_id: uuid.UUID, db: DbSession, company: CurrentCompany, user: CurrentUser
) -> CvDownload:
    application = await _get_or_404(db, company, application_id)
    await access_log.record(
        db,
        company=company,
        application_id=application.id,
        action=access_log.CV_DOWNLOAD,
        user=user,
    )
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
    application_id: uuid.UUID, db: DbSession, company: CurrentCompany, user: CurrentUser
) -> list[QuizAnswerReview]:
    application = await _get_or_404(db, company, application_id)
    await access_log.record(
        db,
        company=company,
        application_id=application.id,
        action=access_log.QUIZ_ANSWERS,
        user=user,
    )
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
