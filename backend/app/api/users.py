import uuid

from fastapi import APIRouter, BackgroundTasks, HTTPException, status

from app.api.deps import AdminUser, CurrentCompany, CurrentUser, DbSession
from app.core.config import settings
from app.core.security import create_invite_token
from app.models import Company, User, UserInvite
from app.schemas.users import (
    AvailabilityIn,
    AvailabilityOut,
    DayWindow,
    InviteCreate,
    InviteOut,
    TeamUserOut,
    UserCreate,
    UserUpdate,
)
from app.services import email as email_service
from app.services import google_calendar
from app.services import interviews as interviews_service
from app.services import invites as invites_service
from app.services import users as users_service

# every route requires an admin of the current company
router = APIRouter(prefix="/users", tags=["users"], dependencies=[])


# /me routes stay ABOVE any /{user_id} routes so "me" never parses as an id.
@router.get("/me/google-calendar")
async def my_google_calendar(db: DbSession, user: CurrentUser) -> dict[str, object]:
    """Calendar-connection state for the Account card. Never exposes tokens."""
    credential = await google_calendar.get_credential(db, user)
    return {
        "connected": credential is not None,
        "google_email": credential.google_email if credential is not None else None,
        "needs_reconnect": bool(credential is not None and credential.last_refresh_error),
    }


@router.delete("/me/google-calendar", status_code=status.HTTP_204_NO_CONTENT)
async def disconnect_google_calendar(db: DbSession, user: CurrentUser) -> None:
    await google_calendar.remove_credentials(db, user)


@router.get("/me/availability", response_model=AvailabilityOut)
async def my_availability(user: CurrentUser) -> AvailabilityOut:
    tz, windows = interviews_service.effective_availability(user)
    days = {
        day: DayWindow(start=f"{start:%H:%M}", end=f"{end:%H:%M}")
        for day, (start, end) in windows.items()
    }
    return AvailabilityOut(timezone=tz or "", days=days, is_default=tz is None)


@router.put("/me/availability", response_model=AvailabilityOut)
async def set_availability(
    payload: AvailabilityIn, db: DbSession, user: CurrentUser
) -> AvailabilityOut:
    user.interview_availability = {
        "timezone": payload.timezone,
        "days": {day: {"start": w.start, "end": w.end} for day, w in payload.days.items()},
    }
    await db.commit()
    return AvailabilityOut(timezone=payload.timezone, days=payload.days, is_default=False)


@router.get("", response_model=list[TeamUserOut])
async def list_users(db: DbSession, company: CurrentCompany, _admin: AdminUser) -> list[User]:
    return await users_service.list_users(db, company)


@router.post("", response_model=TeamUserOut, status_code=status.HTTP_201_CREATED)
async def create_user(
    payload: UserCreate, db: DbSession, company: CurrentCompany, _admin: AdminUser
) -> User:
    try:
        return await users_service.create_user(db, company, payload)
    except users_service.EmailTakenError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A user with this email already exists",
        ) from None


def _schedule_invite_email(
    background: BackgroundTasks, company: Company, inviter: User, invite: UserInvite
) -> None:
    base = settings.public_base_url.rstrip("/")
    background.add_task(
        email_service.send_team_invite,
        to=invite.email,
        company_name=company.name,
        inviter_email=inviter.email,
        role=invite.role.value,
        invite_url=f"{base}/invite/{create_invite_token(invite.id)}",
        expires_at=invite.expires_at,
        brand_primary=(company.theme or {}).get("primary_color"),
    )


@router.get("/invites", response_model=list[InviteOut])
async def list_invites(
    db: DbSession, company: CurrentCompany, _admin: AdminUser
) -> list[UserInvite]:
    return await invites_service.list_invites(db, company)


@router.post("/invites", response_model=InviteOut, status_code=status.HTTP_201_CREATED)
async def create_invite(
    payload: InviteCreate,
    db: DbSession,
    company: CurrentCompany,
    admin: AdminUser,
    background: BackgroundTasks,
) -> UserInvite:
    try:
        invite = await invites_service.create_invite(db, company, payload)
    except invites_service.EmailTakenError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A user with this email already exists",
        ) from None
    except invites_service.InviteExistsError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This email already has a pending invite",
        ) from None
    _schedule_invite_email(background, company, admin, invite)
    return invite


@router.post("/invites/{invite_id}/resend", response_model=InviteOut)
async def resend_invite(
    invite_id: uuid.UUID,
    db: DbSession,
    company: CurrentCompany,
    admin: AdminUser,
    background: BackgroundTasks,
) -> UserInvite:
    invite = await invites_service.get_invite(db, company, invite_id)
    if invite is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invite not found")
    invite = await invites_service.resend_invite(db, invite)
    _schedule_invite_email(background, company, admin, invite)
    return invite


@router.delete("/invites/{invite_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_invite(
    invite_id: uuid.UUID, db: DbSession, company: CurrentCompany, _admin: AdminUser
) -> None:
    invite = await invites_service.get_invite(db, company, invite_id)
    if invite is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invite not found")
    await invites_service.revoke_invite(db, invite)


@router.patch("/{user_id}", response_model=TeamUserOut)
async def update_user(
    user_id: uuid.UUID,
    payload: UserUpdate,
    db: DbSession,
    company: CurrentCompany,
    _admin: AdminUser,
) -> User:
    user = await users_service.get_user(db, company, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    try:
        return await users_service.update_user(db, company, user, payload)
    except users_service.LastAdminError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Cannot remove the company's last active admin",
        ) from None


@router.post("/{user_id}/anonymize", status_code=status.HTTP_204_NO_CONTENT)
async def anonymize_user(
    user_id: uuid.UUID,
    db: DbSession,
    company: CurrentCompany,
    admin: AdminUser,
) -> None:
    """GDPR removal for a teammate: tombstone in place (hard delete is
    FK-blocked by their interviews). Cannot be undone."""
    user = await users_service.get_user(db, company, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    try:
        await users_service.anonymize_user(db, company, user, actor_user_id=admin.id)
    except users_service.LastAdminError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Cannot remove the company's last active admin",
        ) from None
    except users_service.HasUpcomingInterviewsError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Reassign or cancel their upcoming interviews first",
        ) from None
