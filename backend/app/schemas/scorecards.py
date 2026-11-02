"""Scorecard request, submit and read shapes (spec: SCORECARDS_SPEC). The
template shapes live in schemas.scorecard_template."""

import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.models import Scorecard, User
from app.models.scorecard import Recommendation
from app.schemas.scorecard_template import ScorecardCriterion
from app.services import scorecards as scorecards_service
from app.services.scorecards import State

_EDITED_AFTER_SECONDS = 1


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

    @classmethod
    def from_row(cls, row: Scorecard, user: User, *, now: datetime) -> "ScorecardOut":
        """``user`` is the reader: only the row's own reviewer may edit, inside
        the window."""
        state = scorecards_service.state_of(row)
        submitted = row.submitted_at
        can_edit = (
            state == "submitted"
            and submitted is not None
            and now - submitted < scorecards_service.EDIT_WINDOW
            and row.reviewer_user_id == user.id
        )
        edited = (
            submitted is not None
            and (row.updated_at - submitted).total_seconds() > _EDITED_AFTER_SECONDS
        )
        return cls(
            id=row.id,
            application_id=row.application_id,
            reviewer_user_id=row.reviewer_user_id,
            reviewer_label=scorecards_service.reviewer_label(row.reviewer),
            requested_by_label=row.requested_by.display_label if row.requested_by else None,
            interview_id=row.interview_id,
            requested_at=row.requested_at,
            due_from=row.due_from,
            submitted_at=row.submitted_at,
            dismissed_at=row.dismissed_at,
            declined_at=row.declined_at,
            state=state,
            waiting_days=scorecards_service.waiting_days(row, now=now),
            criteria=[ScorecardCriterion(**c) for c in row.criteria_snapshot],
            ratings=dict(row.ratings),
            recommendation=row.recommendation,
            comment=row.comment,
            edited=edited,
            can_edit=can_edit,
        )


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
