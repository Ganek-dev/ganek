"""Candidate-facing schemas.

Deliberately minimal: no ids, no status, no quiz_config, no timestamps
beyond published_at. What is not serialized cannot leak.
"""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, HttpUrl

from app.models import EmploymentType, RemotePolicy


class PublicJobSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    slug: str
    title: str
    location: str
    remote_policy: RemotePolicy
    employment_type: EmploymentType
    salary_min: int | None
    salary_max: int | None
    salary_currency: str | None
    tags: list[str]
    published_at: datetime | None


class PublicJobDetail(PublicJobSummary):
    description_md: str


class PublicCompanyOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    slug: str
    name: str
    description: str
    logo_url: str | None
    website: str | None
    socials: dict[str, Any]
    theme: dict[str, Any]


class PublicCompanyPage(BaseModel):
    company: PublicCompanyOut
    jobs: list[PublicJobSummary]


class CvUploadTicket(BaseModel):
    upload_url: str
    object_key: str
    content_type: str
    max_size_mb: int


class ApplicationSubmit(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    email: EmailStr
    message: str | None = Field(default=None, max_length=5000)
    github: HttpUrl | None = None
    linkedin: HttpUrl | None = None
    portfolio: HttpUrl | None = None
    cv_object_key: str = Field(min_length=1, max_length=500)
    cv_filename: str = Field(min_length=1, max_length=255, pattern=r"(?i)\.pdf$")

    def links(self) -> dict[str, str]:
        return {
            key: str(url)
            for key, url in (
                ("github", self.github),
                ("linkedin", self.linkedin),
                ("portfolio", self.portfolio),
            )
            if url is not None
        }


class ApplicationReceived(BaseModel):
    status: str = "received"
    quiz_token: str | None = None


class QuizOptionOut(BaseModel):
    key: str
    text_md: str


class QuizQuestionOut(BaseModel):
    """Candidate-facing question. correct_key/explanation MUST never appear here."""

    id: str
    prompt_md: str
    options: list[QuizOptionOut]  # in served (shuffled) order
    time_limit_seconds: int
    deadline_at: datetime
    index: int
    total: int


class QuizStateOut(BaseModel):
    status: str
    answered: int
    total: int


class QuizNextOut(BaseModel):
    done: bool
    question: QuizQuestionOut | None = None


class QuizAnswerIn(BaseModel):
    question_id: str = Field(min_length=1, max_length=100)
    answer_key: str = Field(pattern=r"^[a-d]$")


class QuizAnswerOut(BaseModel):
    recorded: bool = True


class QuizEvent(BaseModel):
    type: Literal["blur", "paste", "resize"]
    duration_ms: int | None = Field(default=None, ge=0, le=600_000)
    question_id: str | None = Field(default=None, max_length=100)


class QuizEventsIn(BaseModel):
    events: list[QuizEvent] = Field(max_length=100)


class QuizEventsOut(BaseModel):
    recorded: bool = True
