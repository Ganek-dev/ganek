import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field


class ActivityOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    type: str
    payload: dict[str, object]
    actor_email: str | None
    application_id: uuid.UUID | None
    created_at: datetime


class TaskCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    note: str = Field(default="", max_length=2000)
    due_date: date | None = None
    assignee_user_id: uuid.UUID | None = None


class TaskUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    note: str | None = Field(default=None, max_length=2000)
    due_date: date | None = None
    done: bool | None = None


class TaskOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    note: str
    due_date: date | None
    done_at: datetime | None
    assignee_user_id: uuid.UUID | None
    created_by: uuid.UUID | None
    created_at: datetime


class TodayEvent(BaseModel):
    start: str | None
    summary: str
    hangout_link: str | None


class TodayOut(BaseModel):
    source: str  # "google" | "ganek"
    events: list[TodayEvent]
