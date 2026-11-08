import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class OpsTenantOut(BaseModel):
    id: uuid.UUID
    slug: str
    name: str
    created_at: datetime
    suspended_at: datetime | None
    suspension_reason: str | None
    users: int
    jobs: int


class SuspendRequest(BaseModel):
    # shown to the tenant's users at sign-in, so it is required
    reason: str = Field(min_length=1, max_length=500)
