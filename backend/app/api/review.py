import uuid

from fastapi import APIRouter, HTTPException, status

from app.api.deps import CurrentCompany, CurrentUser, DbSession
from app.core.access import can_open_application
from app.models import UserRole
from app.schemas.review import ReviewApplicationListItem, ReviewApplicationOut
from app.services import access_log
from app.services import applications as applications_service
from app.services import review as review_service

router = APIRouter(prefix="/review", tags=["review"])


@router.get("/applications", response_model=list[ReviewApplicationListItem])
async def list_review_applications(
    db: DbSession, user: CurrentUser
) -> list[ReviewApplicationListItem]:
    """Summary-level like the staff list, so no access-log row."""
    if user.role is not UserRole.REVIEWER:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Recruiters work from the applicants page",
        )
    return await review_service.list_applications(db, user)


@router.get("/applications/{application_id}", response_model=ReviewApplicationOut)
async def get_review_application(
    application_id: uuid.UUID, db: DbSession, company: CurrentCompany, user: CurrentUser
) -> ReviewApplicationOut:
    application = (
        await applications_service.get_application(db, company, application_id)
        if await can_open_application(db, user, application_id)
        else None
    )
    if application is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Application not found")
    view = await review_service.judging_view(db, company, user, application)
    # one row per action, like the staff routes for the same data
    actions = [access_log.VIEW]
    if view.cv_url is not None:
        actions.append(access_log.CV_DOWNLOAD)
    if view.quiz is not None:
        actions.append(access_log.QUIZ_ANSWERS)
    for action in actions:
        await access_log.record(
            db, company=company, application_id=application.id, action=action, user=user
        )
    return view
