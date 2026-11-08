import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.schemas.dsar import DsarBundle


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


class OpsExportUser(BaseModel):
    # account metadata only: password hashes, TOTP secrets, recovery codes
    # and token versions never leave the database
    email: str
    display_name: str | None
    role: str
    is_active: bool
    created_at: datetime
    last_login_at: datetime | None


class OpsExportJob(BaseModel):
    slug: str
    title: str
    status: str
    department: str
    location: str
    remote_policy: str
    employment_type: str
    description_md: str
    created_at: datetime
    published_at: datetime | None
    closed_at: datetime | None


class OpsTenantExport(BaseModel):
    """A whole tenant, for an export on request (offboarding, portability).
    Candidates reuse the DSAR bundle shape (one bundle per candidate)."""

    generated_at: datetime
    tenant: OpsTenantOut
    users: list[OpsExportUser]
    jobs: list[OpsExportJob]
    candidates: list[DsarBundle]
