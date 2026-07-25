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
    attempts_total: int = 0
    attempts_completed: int = 0
    completion_rate: float | None = None  # None when no attempts yet
    avg_score: float | None = None  # across completed attempts
    median_score: float | None = None  # across completed attempts
    avg_duration_seconds: float | None = None  # completed_at - started_at
    # Histogram of completed scores in 10-point buckets: index 0 = [0, 10),
    # ..., index 9 = [90, 100]. Purely informational — any "pass" line drawn
    # over it is visualization only (the tool never auto-rejects).
    score_distribution: list[int] = []


class PerJobStats(BaseModel):
    job_id: uuid.UUID
    title: str
    status: JobStatus
    applications: int
    new: int


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
