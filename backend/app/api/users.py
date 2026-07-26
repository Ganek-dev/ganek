import uuid

from fastapi import APIRouter, BackgroundTasks, HTTPException, status

from app.api.deps import AdminUser, CurrentCompany, DbSession
from app.core.config import settings
from app.core.security import create_invite_token
from app.models import Company, User, UserInvite
from app.schemas.users import InviteCreate, InviteOut, TeamUserOut, UserCreate, UserUpdate
from app.services import email as email_service
from app.services import invites as invites_service
from app.services import users as users_service

# every route requires an admin of the current company
router = APIRouter(prefix="/users", tags=["users"], dependencies=[])


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
