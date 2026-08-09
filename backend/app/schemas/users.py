import uuid
from datetime import datetime, time
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator, model_validator

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


DayKey = Literal["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


class DayWindow(BaseModel):
    start: str
    end: str

    @field_validator("start", "end")
    @classmethod
    def on_half_hour_grid(cls, v: str) -> str:
        parsed = time.fromisoformat(v)  # raises ValueError -> pydantic error
        if parsed.minute not in (0, 30) or parsed.second or parsed.microsecond:
            raise ValueError("times must be on the 30-minute grid")
        return v

    @model_validator(mode="after")
    def ordered(self) -> "DayWindow":
        if time.fromisoformat(self.start) >= time.fromisoformat(self.end):
            raise ValueError("start must be before end")
        return self


class AvailabilityIn(BaseModel):
    timezone: str = Field(min_length=1, max_length=60)
    days: dict[DayKey, DayWindow]

    @field_validator("timezone")
    @classmethod
    def known_zone(cls, v: str) -> str:
        try:
            ZoneInfo(v)
        except (ZoneInfoNotFoundError, ValueError):
            raise ValueError(f"unknown timezone {v!r}") from None
        return v


class AvailabilityOut(BaseModel):
    timezone: str
    days: dict[DayKey, DayWindow]
    is_default: bool
