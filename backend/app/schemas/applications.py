"""Recruiter-facing application schemas."""

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, EmailStr, Field

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
    # opt-in: emails the candidate for stages with a template (22a/22b);
    # silently ignored for the rest
    notify_candidate: bool = False


class BulkRejectIn(BaseModel):
    application_ids: list[uuid.UUID] = Field(min_length=1, max_length=100)
    # opt-in: emails each newly-rejected candidate (22b); already-rejected/
    # withdrawn/foreign/unknown ids are silently skipped, no email either way
    notify_candidates: bool = False


class BulkRejectOut(BaseModel):
    rejected: int
    skipped: int


class EmailDeliveryOut(BaseModel):
    """One outbox row for the applicant panel's delivery trail (M5.7 H4).

    Deliberately WITHOUT the payload — the panel needs kind + state, not
    the stored kwargs (which carry capability URLs)."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    kind: str
    status: str
    attempts: int
    last_error: str | None
    created_at: datetime
    sent_at: datetime | None


class CvDownload(BaseModel):
    download_url: str


class EraseCandidateOut(BaseModel):
    applications: int
    google_event_failures: int


class CandidateEmailUpdate(BaseModel):
    email: EmailStr


class ReviewIntegrityEvent(BaseModel):
    type: str
    duration_ms: int | None


class NoteCreate(BaseModel):
    body: str = Field(min_length=1, max_length=4000)


class NoteOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    body: str
    author_email: str | None
    created_at: datetime


class QuizAnswerReview(BaseModel):
    """One answered (or timed-out) question, recruiter-facing.

    correct_key IS present — recruiters review answers. The hard rule
    forbids it in candidate-facing schemas only.
    """

    question_id: str
    prompt_md: str
    options: dict[str, Any]
    correct_key: str
    explanation_md: str
    tags: list[str]
    answer_key: str | None  # None = time ran out
    is_correct: bool
    response_ms: int | None
    integrity_events: list[ReviewIntegrityEvent]
