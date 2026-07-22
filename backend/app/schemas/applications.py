"""Recruiter-facing application schemas."""

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict

from app.models import ApplicationStage, AttemptStatus


class CandidateOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    email: str
    links: dict[str, Any]


class QuizResultOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    status: AttemptStatus
    score: float | None
    per_tag_scores: dict[str, Any]
    completed_at: datetime | None
    question_ids: list[str]
    integrity: dict[str, Any]


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
    quiz_attempt: QuizResultOut | None
    created_at: datetime


class StageUpdate(BaseModel):
    stage: ApplicationStage


class CvDownload(BaseModel):
    download_url: str
