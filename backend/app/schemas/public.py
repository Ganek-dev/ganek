"""Candidate-facing schemas.

Deliberately minimal: no ids, no status, no quiz_config, no timestamps
beyond published_at. What is not serialized cannot leak.
"""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict

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
