"""The reviewer judging view (spec 4.5). Built field by field for this surface:
no correct key, option text, candidate email, notes, integrity telemetry,
rejection reason or preferred answer (test-enforced)."""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel

from app.schemas.public import StatusScreeningAnswer
from app.schemas.scorecards import ScorecardOut
from app.services.scorecards import State

QuizOutcome = Literal["correct", "wrong", "timed_out", "unanswered"]


class ReviewQuizQuestion(BaseModel):
    prompt: str
    outcome: QuizOutcome


class ReviewQuizSummary(BaseModel):
    score: float | None
    correct: int
    total: int
    timed_out: int
    questions: list[ReviewQuizQuestion]


class ReviewInterview(BaseModel):
    scheduled_start: datetime | None
    duration_minutes: int
    location: str | None
    timezone: str


class ReviewApplicationListItem(BaseModel):
    application_id: uuid.UUID
    candidate_name: str
    job_title: str
    stage_label: str
    scorecard_state: State | None
    scorecard_due_from: datetime | None
    scorecard_submitted_at: datetime | None
    interview_start: datetime | None


class ReviewApplicationOut(BaseModel):
    application_id: uuid.UUID
    candidate_name: str
    job_title: str
    cv_url: str | None
    # question and answer only, not the recruiter-facing snapshot (0039)
    screening_answers: list[StatusScreeningAnswer]
    quiz: ReviewQuizSummary | None
    interview: ReviewInterview | None
    mine: ScorecardOut | None
    others: list[ScorecardOut]
    hidden_until_submitted: bool
