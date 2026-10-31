"""Recruiter-facing application schemas."""

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator, model_validator

from app.models import ApplicationStage, AttemptStatus
from app.services.rejection_reasons import ReasonKey


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
    time_multiplier: float
    integrity: dict[str, Any]


class AccessEntryOut(BaseModel):
    """One read of this candidate: a person (session) or an API key."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    action: str
    actor_email: str | None
    actor_label: str | None
    api_key_name: str | None
    created_at: datetime


class TimelineEventOut(BaseModel):
    """One row of the applicant panel's timeline (board card "Candidate
    timeline"): a merged read model, see services/timeline.py. ``kind`` is
    an activity type or one of applied / quiz.invited / quiz.started /
    quiz.completed / quiz.expired / email; ``payload`` carries the facts
    the copy needs (from/to, score, template + status, reason)."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    kind: str
    at: datetime
    actor_label: str | None
    actor_email: str | None
    payload: dict[str, object]


class AccessLogRowOut(AccessEntryOut):
    """Company-wide row: the entry plus who the candidate was."""

    application_id: uuid.UUID
    candidate_name: str
    job_title: str


class AccessLogPage(BaseModel):
    items: list[AccessLogRowOut]
    total: int


class ExtraTimeIn(BaseModel):
    """Recruiter-side accommodation: 1 removes it, 1.5 and 2 are the grants."""

    time_multiplier: float

    @field_validator("time_multiplier")
    @classmethod
    def _known_multiplier(cls, value: float) -> float:
        if value not in (1.0, 1.5, 2.0):
            raise ValueError("time_multiplier must be 1, 1.5 or 2")
        return float(value)


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
    stage_changed_at: datetime
    # internal, recruiter-facing only (0036); never in a candidate schema
    rejection_reason: str | None
    rejection_note: str | None


class ApplicationPage(BaseModel):
    """One page of the pipeline (M5.7 H4). `stage_counts` covers the whole
    set the other filters match - the stage pills are how you switch
    stages, so the stage filter never narrows them."""

    items: list[ApplicationOut]
    total: int
    stage_counts: dict[str, int]
    # source facet for the filter control: company-wide distinct values,
    # NULL folded into "direct"
    sources: list[str] = []


class RejectionFields(BaseModel):
    """The optional internal reason (PR 2): a fixed key and a free note,
    stripped, empty becomes null. Never part of an email."""

    rejection_reason: ReasonKey | None = None
    rejection_note: str | None = Field(default=None, max_length=1000)
    # the email template for the mail this move sends (PR 3): a workspace
    # template id, "builtin" for the Ganek default, None for the kind's
    # default; ignored when no mail goes out
    template_id: uuid.UUID | Literal["builtin"] | None = None

    @field_validator("rejection_note")
    @classmethod
    def _strip_note(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None

    @property
    def has_reason(self) -> bool:
        return self.rejection_reason is not None or self.rejection_note is not None


class StageUpdate(RejectionFields):
    stage: ApplicationStage
    # opt-in: emails the candidate for stages with a template (22a/22b);
    # silently ignored for the rest
    notify_candidate: bool = False

    @model_validator(mode="after")
    def _reason_needs_rejected(self) -> "StageUpdate":
        if self.has_reason and self.stage is not ApplicationStage.REJECTED:
            raise ValueError("rejection reason needs the rejected stage")
        return self


class BulkRejectIn(RejectionFields):
    application_ids: list[uuid.UUID] = Field(min_length=1, max_length=100)
    # opt-in: emails each newly-rejected candidate (22b); already-rejected/
    # withdrawn/foreign/unknown ids are silently skipped, no email either way
    notify_candidates: bool = False


class BulkRejectOut(BaseModel):
    rejected: int
    skipped: int


class BulkStageIn(RejectionFields):
    """The bulk bar's "Move to": same cap as bulk reject; withdrawn is the
    candidate's stage and never a recruiter target."""

    application_ids: list[uuid.UUID] = Field(min_length=1, max_length=100)
    stage: ApplicationStage
    notify_candidates: bool = False

    @field_validator("stage")
    @classmethod
    def _not_withdrawn(cls, value: ApplicationStage) -> ApplicationStage:
        if value is ApplicationStage.WITHDRAWN:
            raise ValueError("withdrawn is set by the candidate, not the team")
        return value

    @model_validator(mode="after")
    def _reason_needs_rejected(self) -> "BulkStageIn":
        if self.has_reason and self.stage is not ApplicationStage.REJECTED:
            raise ValueError("rejection reason needs the rejected stage")
        return self


class BulkStageOut(BaseModel):
    updated: int
    skipped: int


EmailKind = Literal["quiz_invite", "quiz_reminder", "stage_advance", "rejection"]


class EmailPreviewOut(BaseModel):
    """A candidate stage mail rendered for one application: what the
    recruiter reads in the preview and what the sender delivers."""

    kind: EmailKind
    subject: str
    text: str
    html: str


class EmailDeliveryOut(BaseModel):
    """One outbox row for the applicant panel's delivery trail (M5.7 H4).

    Deliberately WITHOUT the payload - the panel needs kind + state, not
    the stored kwargs (which carry capability URLs). ``subject`` and
    ``text`` are the mail as rendered at delivery (PR 4), None before."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: uuid.UUID
    kind: str
    status: str
    attempts: int
    last_error: str | None
    created_at: datetime
    sent_at: datetime | None
    subject: str | None = Field(default=None, validation_alias="rendered_subject")
    text: str | None = Field(default=None, validation_alias="rendered_text")


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

    correct_key IS present - recruiters review answers. The hard rule
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
