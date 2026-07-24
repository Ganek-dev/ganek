import uuid
from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models import EmploymentType, JobStatus, RemotePolicy

DifficultyLevel = Annotated[int, Field(ge=1, le=5)]


class QuizConfigSchema(BaseModel):
    enabled: bool = False
    tags: list[str] | None = Field(
        default=None, max_length=10, description="Question pool tags; None = use the job's tags"
    )
    question_count: int = Field(default=6, ge=1, le=20)
    include_company_questions: bool = True
    time_limit_seconds: int | None = Field(
        default=20,
        ge=10,
        le=60,
        description="Seconds per question; None = each question's own limit",
    )
    difficulties: list[DifficultyLevel] | None = Field(
        default=None, description="Allowed difficulty levels 1-5; None = all"
    )
    exclude_ids: list[str] = Field(
        default_factory=list, max_length=500, description="Question ids excluded from this job"
    )


class QuizPreviewQuestion(BaseModel):
    """Pool entry in the recruiter-side quiz preview. Admin-side only."""

    id: str
    source: str  # "seed" (open bank) or "company"
    tags: list[str]
    difficulty: int
    prompt_md: str
    options: dict[str, str]
    correct_key: str
    excluded: bool  # in this job's exclude_ids
    blocked: bool  # on the company-wide blocklist


class QuizPreviewOut(BaseModel):
    enabled: bool
    tags: list[str]
    question_count: int
    time_limit_seconds: int | None
    difficulties: list[int]
    pool: list[QuizPreviewQuestion]
    eligible_count: int
    eligible_by_tag: dict[str, int]
    sample_question_ids: list[str]


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
    quiz_config: QuizConfigSchema = Field(default_factory=QuizConfigSchema)

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
    quiz_config: QuizConfigSchema | None = None


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
    quiz_config: QuizConfigSchema
    published_at: datetime | None
    created_at: datetime
    updated_at: datetime
