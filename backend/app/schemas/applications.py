"""Recruiter-facing application schemas."""

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict

from app.models import ApplicationStage


class CandidateOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    email: str
    links: dict[str, Any]


class ApplicationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    job_id: uuid.UUID
    candidate: CandidateOut
    cv_filename: str
    cv_size: int
    message: str | None
    stage: ApplicationStage
    source: str | None
    created_at: datetime


class StageUpdate(BaseModel):
    stage: ApplicationStage


class CvDownload(BaseModel):
    download_url: str
