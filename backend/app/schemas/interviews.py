import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.models import InterviewStatus


class SlotPreviewRequest(BaseModel):
    interviewer_user_id: uuid.UUID
    duration_minutes: Literal[15, 30, 45, 60]
    timezone: str = Field(min_length=1, max_length=60)


class InterviewCreate(SlotPreviewRequest):
    title: str = Field(default="Hiring manager interview", min_length=1, max_length=200)
    description: str = Field(default="", max_length=2000)
    # the recruiter-pruned offer; server-generated slots round-tripped
    slots: list[datetime] = Field(min_length=1, max_length=40)


class InterviewOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    status: InterviewStatus
    interviewer_user_id: uuid.UUID
    interviewer_email: str
    title: str
    description: str
    duration_minutes: int
    timezone: str
    offered_slots: list[datetime]
    scheduled_start: datetime | None
    meet_url: str | None
    created_at: datetime
