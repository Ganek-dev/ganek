import uuid
from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, HTTPException, Query, Response, status
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.api.deps import CurrentCompany, CurrentUser, DbSession
from app.core import urls
from app.models import Application, Scorecard, User
from app.schemas.scorecards import (
    MyScorecardOut,
    ScorecardCriterion,
    ScorecardOut,
    ScorecardRequestIn,
    ScorecardSubmitIn,
)
from app.services import applications as applications_service
from app.services import scorecards as scorecards_service

router = APIRouter(prefix="/scorecards", tags=["scorecards"])

_EDITED_AFTER_SECONDS = 1


def _to_out(row: Scorecard, user: User, *, now: datetime) -> ScorecardOut:
    state = scorecards_service.state_of(row)
    submitted = row.submitted_at
    can_edit = (
        state == "submitted"
        and submitted is not None
        and now - submitted < scorecards_service.EDIT_WINDOW
        and row.reviewer_user_id == user.id
    )
    edited = (
        submitted is not None
        and (row.updated_at - submitted).total_seconds() > _EDITED_AFTER_SECONDS
    )
    return ScorecardOut(
        id=row.id,
        application_id=row.application_id,
        reviewer_user_id=row.reviewer_user_id,
        reviewer_label=scorecards_service.reviewer_label(row.reviewer),
        requested_by_label=row.requested_by.display_label if row.requested_by else None,
        interview_id=row.interview_id,
        requested_at=row.requested_at,
        due_from=row.due_from,
        submitted_at=row.submitted_at,
        dismissed_at=row.dismissed_at,
        declined_at=row.declined_at,
        state=state,
        waiting_days=scorecards_service.waiting_days(row, now=now),
        criteria=[ScorecardCriterion(**c) for c in row.criteria_snapshot],
        ratings=dict(row.ratings),
        recommendation=row.recommendation,
        comment=row.comment,
        edited=edited,
        can_edit=can_edit,
    )


async def _application_or_404(
    db: DbSession, company: CurrentCompany, application_id: uuid.UUID
) -> Application:
    application = await applications_service.get_application(db, company, application_id)
    if application is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Application not found")
    return application


async def _mine_or_404(db: DbSession, user: User, application_id: uuid.UUID) -> Scorecard:
    # get_mine scopes by the caller's company and reviewer id: nobody can act
    # on another reviewer's row
    row = await scorecards_service.get_mine(db, user=user, application_id=application_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No scorecard for you")
    return row


@router.get("/mine", response_model=list[MyScorecardOut])
async def my_scorecards(
    db: DbSession,
    company: CurrentCompany,
    user: CurrentUser,
    state: Literal["open", "all"] = Query(default="open"),
) -> list[MyScorecardOut]:
    rows = await scorecards_service.list_mine(db, user=user, state=state)
    if not rows:
        return []
    apps = (
        (
            await db.execute(
                select(Application)
                .where(
                    Application.company_id == user.company_id,
                    Application.id.in_({r.application_id for r in rows}),
                )
                .options(selectinload(Application.candidate), selectinload(Application.job))
            )
        )
        .scalars()
        .all()
    )
    by_id = {a.id: a for a in apps}
    now = datetime.now(UTC)
    reviewer_role = str(user.role) == "reviewer"
    out: list[MyScorecardOut] = []
    for row in rows:
        application = by_id[row.application_id]
        out.append(
            MyScorecardOut(
                id=row.id,
                application_id=row.application_id,
                candidate_name=application.candidate.name,
                job_title=application.job.title,
                requested_by_label=row.requested_by.display_label if row.requested_by else None,
                requested_at=row.requested_at,
                due_from=row.due_from,
                waiting_days=scorecards_service.waiting_days(row, now=now),
                state=scorecards_service.state_of(row),
                submitted_at=row.submitted_at,
                href=urls.scorecard_url(company, row.application_id, reviewer=reviewer_role),
            )
        )
    return out


@router.get("/applications/{application_id}", response_model=list[ScorecardOut])
async def list_scorecards(
    application_id: uuid.UUID, db: DbSession, company: CurrentCompany, user: CurrentUser
) -> list[ScorecardOut]:
    application = await _application_or_404(db, company, application_id)
    rows = await scorecards_service.list_for_application(
        db, company_id=company.id, application_id=application.id
    )
    now = datetime.now(UTC)
    return [_to_out(r, user, now=now) for r in rows]


@router.post(
    "/applications/{application_id}",
    response_model=ScorecardOut,
    status_code=status.HTTP_201_CREATED,
)
async def request_scorecard(
    application_id: uuid.UUID,
    payload: ScorecardRequestIn,
    db: DbSession,
    company: CurrentCompany,
    user: CurrentUser,
) -> ScorecardOut:
    application = await _application_or_404(db, company, application_id)
    reviewer = (
        await db.execute(
            select(User).where(
                User.id == payload.reviewer_user_id,
                User.company_id == company.id,
                User.is_active.is_(True),
            )
        )
    ).scalar_one_or_none()
    if reviewer is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Reviewer not found")
    try:
        row = await scorecards_service.request(
            db, application=application, reviewer=reviewer, requested_by=user
        )
    except scorecards_service.SelfRequestError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="You cannot request your own scorecard"
        ) from None
    except scorecards_service.AlreadyOpenError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This reviewer already has a scorecard request",
        ) from None
    await db.refresh(row)  # request committed; reload for the response
    return _to_out(row, user, now=datetime.now(UTC))


@router.post("/{scorecard_id}/dismiss", status_code=status.HTTP_204_NO_CONTENT)
async def dismiss_scorecard(
    scorecard_id: uuid.UUID, db: DbSession, company: CurrentCompany, user: CurrentUser
) -> Response:
    row = (
        await db.execute(
            select(Scorecard).where(
                Scorecard.id == scorecard_id, Scorecard.company_id == company.id
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Scorecard not found")
    try:
        await scorecards_service.dismiss(db, row, actor_user_id=user.id)
    except scorecards_service.NotOpenError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Scorecard is not open"
        ) from None
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.put("/applications/{application_id}/mine", response_model=ScorecardOut)
async def submit_my_scorecard(
    application_id: uuid.UUID, payload: ScorecardSubmitIn, db: DbSession, user: CurrentUser
) -> ScorecardOut:
    row = await _mine_or_404(db, user, application_id)
    try:
        await scorecards_service.submit(
            db,
            row,
            ratings=payload.ratings,
            recommendation=payload.recommendation,
            comment=payload.comment,
        )
    except scorecards_service.NotOpenError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Scorecard is not open"
        ) from None
    except scorecards_service.EditWindowClosedError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="The edit window has closed"
        ) from None
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from None
    await db.commit()
    await db.refresh(row)
    return _to_out(row, user, now=datetime.now(UTC))


@router.post("/applications/{application_id}/mine/decline", status_code=status.HTTP_204_NO_CONTENT)
async def decline_my_scorecard(
    application_id: uuid.UUID, db: DbSession, user: CurrentUser
) -> Response:
    row = await _mine_or_404(db, user, application_id)
    try:
        await scorecards_service.decline(db, row)
    except scorecards_service.NotOpenError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Scorecard is not open"
        ) from None
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
