import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.models import UserRole


class UserCreate(BaseModel):
    email: EmailStr
    password: str = Field(min_length=10, max_length=128)
    role: UserRole = UserRole.MEMBER


class UserUpdate(BaseModel):
    role: UserRole | None = None
    is_active: bool | None = None


class TeamUserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: EmailStr
    role: UserRole
    is_active: bool
    last_login_at: datetime | None
    created_at: datetime


class InviteCreate(BaseModel):
    email: EmailStr
    role: UserRole = UserRole.MEMBER


class InviteOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: EmailStr
    role: UserRole
    created_at: datetime
    expires_at: datetime


class PublicInviteOut(BaseModel):
    """What the accept page may see before the invitee has an account."""

    email: EmailStr
    company_name: str
    role: UserRole


class InviteAcceptRequest(BaseModel):
    password: str = Field(min_length=10, max_length=128)
