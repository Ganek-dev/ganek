import uuid

from fastapi import APIRouter, HTTPException, status

from app.api.deps import AdminUser, CurrentCompany, DbSession
from app.models import User
from app.schemas.users import TeamUserOut, UserCreate, UserUpdate
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
