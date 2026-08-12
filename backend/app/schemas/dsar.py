"""DSAR export bundle (Art. 15/20) — admin-mediated, candidate-destined.

Everything here ends up in the candidate's hands: recruiter identifiers
(note authors, reissue/review user ids, actor emails) are third-party data
and stay out; bank secrets (correct_key) must never appear. Activity rows
are type+timestamp only — payloads can embed other people's identifiers.
"""

from datetime import datetime
from typing import Any

from pydantic import BaseModel


class DsarAnswer(BaseModel):
    question_id: str
    served_at: datetime | None
    answered_at: datetime | None
    answer_key: str | None
    is_correct: bool


class DsarAttempt(BaseModel):
    status: str
    started_at: datetime | None
    completed_at: datetime | None
    expires_at: datetime | None
    score: float | None
    per_tag_scores: dict[str, Any]
    integrity: dict[str, Any]
    answers: list[DsarAnswer]


class DsarInterview(BaseModel):
    title: str
    timezone: str
    scheduled_start: datetime | None
    status: str
    created_at: datetime


class DsarNote(BaseModel):
    # author deliberately absent: a teammate's identity is third-party data
    body: str
    created_at: datetime


class DsarActivityEntry(BaseModel):
    # payloads deliberately absent: they can embed recruiter identifiers
    type: str
    created_at: datetime


class DsarApplication(BaseModel):
    job_title: str
    stage: str
    source: str | None
    message: str | None
    cv_filename: str | None
    cv_size: int | None
    applied_at: datetime
    cv_download_url: str | None
    quiz_attempts: list[DsarAttempt]
    interviews: list[DsarInterview]
    notes: list[DsarNote]
    activity: list[DsarActivityEntry]


class DsarBundle(BaseModel):
    generated_at: datetime
    controller: dict[str, str]
    candidate: dict[str, Any]
    applications: list[DsarApplication]
