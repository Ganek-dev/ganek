import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models import EmploymentType, JobStatus, RemotePolicy


class JobCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    description_md: str = Field(default="", max_length=50_000)
    location: str = Field(default="", max_length=200)
    remote_policy: RemotePolicy = RemotePolicy.ONSITE
    employment_type: EmploymentType = EmploymentType.FULL_TIME
    salary_min: int | None = Field(default=None, ge=0)
    salary_max: int | None = Field(default=None, ge=0)
    salary_currency: str | None = Field(default=None, min_length=3, max_length=3)
    tags: list[str] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def _salary_range_valid(self) -> "JobCreate":
        if (
            self.salary_min is not None
            and self.salary_max is not None
            and self.salary_min > self.salary_max
        ):
            raise ValueError("salary_min cannot exceed salary_max")
        return self


class JobUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    description_md: str | None = Field(default=None, max_length=50_000)
    location: str | None = Field(default=None, max_length=200)
    remote_policy: RemotePolicy | None = None
    employment_type: EmploymentType | None = None
    salary_min: int | None = Field(default=None, ge=0)
    salary_max: int | None = Field(default=None, ge=0)
    salary_currency: str | None = Field(default=None, min_length=3, max_length=3)
    tags: list[str] | None = Field(default=None, max_length=20)


class JobOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    slug: str
    title: str
    description_md: str
    location: str
    remote_policy: RemotePolicy
    employment_type: EmploymentType
    salary_min: int | None
    salary_max: int | None
    salary_currency: str | None
    tags: list[str]
    status: JobStatus
    published_at: datetime | None
    created_at: datetime
    updated_at: datetime
