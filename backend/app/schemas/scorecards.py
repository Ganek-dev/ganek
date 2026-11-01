"""Scorecard template shapes (spec: SCORECARDS_SPEC). A template is the list
of criteria a reviewer rates; it lives on the company (default) and on each
job (copied on create, never linked)."""

import secrets
import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.models.scorecard import Recommendation
from app.services.scorecards import State

MAX_CRITERIA = 20


class ScorecardCriterion(BaseModel):
    # empty on input = the server assigns one (ensure_criterion_ids)
    id: str = Field(default="", max_length=16)
    label: str = Field(min_length=1, max_length=120)
    hint: str = Field(default="", max_length=300)


def _check_criteria(criteria: list[ScorecardCriterion]) -> None:
    if len(criteria) > MAX_CRITERIA:
        raise ValueError(f"at most {MAX_CRITERIA} criteria")
    given = [c.id for c in criteria if c.id]
    if len(given) != len(set(given)):
        raise ValueError("criterion ids must be unique")


def validate_criteria(value: list[ScorecardCriterion] | None) -> list[ScorecardCriterion] | None:
    """Field-validator body shared by the company and job schemas, so a bad
    template surfaces as a 422 rather than an error in the service."""
    if value is not None:
        _check_criteria(value)
    return value


def ensure_criterion_ids(criteria: list[ScorecardCriterion]) -> list[dict[str, str]]:
    """Dump criteria for storage, filling empty ids with an 8-char token."""
    _check_criteria(criteria)
    taken = {c.id for c in criteria if c.id}
    out: list[dict[str, str]] = []
    for criterion in criteria:
        data = criterion.model_dump()
        if not data["id"]:
            new_id = secrets.token_urlsafe(6)
            while new_id in taken:
                new_id = secrets.token_urlsafe(6)
            taken.add(new_id)
            data["id"] = new_id
        out.append(data)
    return out


class ScorecardRequestIn(BaseModel):
    reviewer_user_id: uuid.UUID


class ScorecardSubmitIn(BaseModel):
    ratings: dict[str, int] = {}
    recommendation: Recommendation
    comment: str | None = Field(default=None, max_length=4000)


class ScorecardOut(BaseModel):
    """Staff-facing: ratings and recommendation never reach a candidate."""

    id: uuid.UUID
    application_id: uuid.UUID
    reviewer_user_id: uuid.UUID | None
    reviewer_label: str
    requested_by_label: str | None
    interview_id: uuid.UUID | None
    requested_at: datetime
    due_from: datetime
    submitted_at: datetime | None
    dismissed_at: datetime | None
    declined_at: datetime | None
    state: State
    waiting_days: int
    criteria: list[ScorecardCriterion]
    ratings: dict[str, int]
    recommendation: Recommendation | None
    comment: str | None
    edited: bool
    can_edit: bool


class MyScorecardOut(BaseModel):
    id: uuid.UUID
    application_id: uuid.UUID
    candidate_name: str
    job_title: str
    requested_by_label: str | None
    requested_at: datetime
    due_from: datetime
    waiting_days: int
    state: State
    submitted_at: datetime | None
    href: str
