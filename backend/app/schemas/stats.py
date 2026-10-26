"""Recruiter dashboard stats. Everything here is tenant-scoped aggregates."""

import uuid
from datetime import date, datetime

from pydantic import BaseModel

from app.models import ApplicationStage, JobStatus


class JobCounts(BaseModel):
    draft: int = 0
    published: int = 0
    closed: int = 0


class ApplicationCounts(BaseModel):
    total: int = 0
    new: int = 0  # stage == "new"
    last_7_days: int = 0


class QuizCounts(BaseModel):
    attempts_total: int = 0  # issued attempts; superseded (invalidated) ones excluded
    attempts_started: int = 0  # opened by the candidate (started_at set)
    attempts_completed: int = 0
    completion_rate: float | None = None  # None when no attempts yet
    avg_score: float | None = None  # across completed attempts
    median_score: float | None = None  # across completed attempts (0–1 fraction)
    avg_duration_seconds: float | None = None  # completed_at - started_at
    # Histogram of completed scores (0–1 fractions) in ten 10%-wide buckets:
    # index 0 = [0, 0.1), ..., index 9 = [0.9, 1.0]. Purely informational —
    # any "pass" line drawn over it is visualization only (never auto-rejects).
    score_distribution: list[int] = []


class PerJobStats(BaseModel):
    job_id: uuid.UUID
    title: str
    status: JobStatus
    applications: int
    new: int
    views_30d: int = 0  # counted job page loads, today and the 29 days before


class ViewCounts(BaseModel):
    """Job page loads that passed the SSR filters (spec 5.5). Not unique."""

    total: int = 0
    last_30_days: int = 0


class DailyPoint(BaseModel):
    day: date  # UTC
    views: int
    applications: int


class WeeklyPoint(BaseModel):
    week_start: date
    count: int


class RecentApplication(BaseModel):
    id: uuid.UUID
    candidate_name: str
    job_id: uuid.UUID
    job_title: str
    stage: ApplicationStage
    quiz_score: float | None
    created_at: datetime


class StatsOverview(BaseModel):
    jobs: JobCounts
    applications: ApplicationCounts
    quiz: QuizCounts
    per_job: list[PerJobStats]
    weekly: list[WeeklyPoint]  # last 8 ISO weeks, oldest first, gaps filled
    recent: list[RecentApplication]  # newest 5


class JobStats(BaseModel):
    """One job's numbers for the overview page. Counts only: nothing here
    ranks, passes or recommends (rule 5)."""

    applications: ApplicationCounts
    last_30_days: int
    by_stage: dict[str, int]  # stage value -> count; stages with 0 are absent
    by_source: dict[str, int]  # source label -> count; NULL counts as "direct"
    quiz: QuizCounts  # attempts of this job's applications; rates None when none
    weekly: list[WeeklyPoint]  # last 8 ISO weeks for this job, gaps filled
    days_open: int | None  # None for drafts; closed_at (or now) minus published_at
    views: ViewCounts
    views_by_source: dict[str, int]  # same labels as by_source (plus "other"), all time
    daily: list[DailyPoint]  # last 30 UTC days, oldest first, gaps filled
