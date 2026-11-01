"""Reports: a cohort funnel, time in stage, time to hire and sources, computed
from stage history. The core is pure (histories in, numbers out); `reports`
loads the cohort and calls it. Medians, never averages; no benchmarks."""

import uuid
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from statistics import median

from sqlalchemy import ColumnElement, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    ActivityLog,
    Application,
    ApplicationStage,
    AttemptStatus,
    Company,
    QuizAttempt,
)
from app.models.application import CLOSED_STAGES
from app.schemas.stats import (
    CohortKpis,
    FunnelStep,
    Period,
    QuizLine,
    ReportsOut,
    SourceRow,
    StageTime,
)
from app.services.activity import STAGE_CHANGED
from app.services.stats import _quiz_counts, _weekly

S = ApplicationStage
FUNNEL_ORDER = (S.NEW, S.SCREENING, S.INTERVIEW, S.OFFER, S.HIRED)
TIMED_STAGES = FUNNEL_ORDER[:-1]  # a stay in hired never ends
OUTCOMES = (S.REJECTED, S.WITHDRAWN)
MIN_N = 3  # a median needs this many values, else "-"
MIN_COHORT = 10  # the diagnosis needs this many applications
PERIOD_DAYS: dict[str, int] = {"30d": 30, "90d": 90, "12m": 365}
PERIOD_WEEKS: dict[str, int] = {"30d": 6, "90d": 14, "12m": 53, "all": 53}


@dataclass(frozen=True)
class StageEvent:
    at: datetime
    from_stage: ApplicationStage | None
    to_stage: ApplicationStage


@dataclass(frozen=True)
class AppHistory:
    id: uuid.UUID
    created_at: datetime
    stage: ApplicationStage
    stage_changed_at: datetime
    decided_at: datetime | None
    source: str | None
    events: tuple[StageEvent, ...]  # ordered by at


def _days(start: datetime, end: datetime) -> int:
    """Whole UTC calendar days between two moments, floor 0 (as waiting_days)."""
    return max((end.astimezone(UTC).date() - start.astimezone(UTC).date()).days, 0)


def _rank(stage: ApplicationStage) -> int:
    return FUNNEL_ORDER.index(stage)


def _median(values: list[int]) -> float | None:
    return float(median(values)) if len(values) >= MIN_N else None


def reached_stage(h: AppHistory) -> ApplicationStage | None:
    """The highest funnel stage the application ever held: its history's `to`
    stages and its current one. Every application starts at new, so the floor
    is new even when it only ever held an outcome."""
    seen = [e.to_stage for e in h.events] + [h.stage]
    ranks = [_rank(stage) for stage in seen if stage in FUNNEL_ORDER]
    return FUNNEL_ORDER[max(ranks, default=0)]


def _reached_rank(h: AppHistory) -> int:
    stage = reached_stage(h)
    return _rank(stage) if stage is not None else -1


def left_from(h: AppHistory) -> tuple[ApplicationStage, ApplicationStage] | None:
    """(outcome, from) of the latest move into the current outcome. A
    withdrawal during a held rejection writes from=rejected, so a `from` that
    is itself an outcome walks back to the earlier row's `from`. None when the
    application is live, or no funnel stage can be found."""
    outcome = h.stage
    if outcome not in OUTCOMES:
        return None
    index = next(
        (i for i in range(len(h.events) - 1, -1, -1) if h.events[i].to_stage is outcome), None
    )
    if index is None:
        return None
    origin = h.events[index].from_stage
    while origin in OUTCOMES:
        index -= 1
        if index < 0:
            return None
        origin = h.events[index].from_stage
    if origin is None or origin not in FUNNEL_ORDER:
        return None
    return outcome, origin


def funnel(histories: list[AppHistory]) -> list[FunnelStep]:
    ranks = [_reached_rank(h) for h in histories]
    reached = [sum(1 for rank in ranks if rank >= i) for i in range(len(FUNNEL_ORDER))]
    rejected: dict[ApplicationStage, int] = defaultdict(int)
    withdrawn: dict[ApplicationStage, int] = defaultdict(int)
    for h in histories:
        left = left_from(h)
        if left is not None:
            (rejected if left[0] is S.REJECTED else withdrawn)[left[1]] += 1
    steps: list[FunnelStep] = []
    for i, stage in enumerate(FUNNEL_ORDER):
        last = i == len(FUNNEL_ORDER) - 1
        steps.append(
            FunnelStep(
                stage=stage,
                reached=reached[i],
                pass_through=(
                    None if last or reached[i] == 0 else round(reached[i + 1] * 100 / reached[i], 1)
                ),
                rejected_from=rejected[stage],
                withdrawn_from=withdrawn[stage],
                still_here=sum(
                    1 for h in histories if h.stage is stage and h.stage not in CLOSED_STAGES
                ),
            )
        )
    return steps


def completed_stays(h: AppHistory) -> list[tuple[ApplicationStage, int]]:
    """(stage, days) of every finished stay in new, screening, interview or
    offer. Entry is the previous row's time, or created_at for new; a row
    whose `from` disagrees with where the history left off has an unknown
    entry, so that stay is skipped."""
    stays: list[tuple[ApplicationStage, int]] = []
    current: ApplicationStage | None = S.NEW
    entered = h.created_at
    for event in h.events:
        if event.from_stage is not None and event.from_stage is not current:
            current = None
        if current in TIMED_STAGES:
            stays.append((current, _days(entered, event.at)))
        current, entered = event.to_stage, event.at
    return stays


def time_in_stage(histories: list[AppHistory], now: datetime) -> list[StageTime]:
    days: dict[ApplicationStage, list[int]] = defaultdict(list)
    oldest: dict[ApplicationStage, int] = {}
    for h in histories:
        for stage, stay in completed_stays(h):
            days[stage].append(stay)
        if h.stage in TIMED_STAGES:
            oldest[h.stage] = max(oldest.get(h.stage, 0), _days(h.stage_changed_at, now))
    return [
        StageTime(
            stage=stage,
            median_days=_median(days[stage]),
            n=len(days[stage]),
            oldest_live_days=oldest.get(stage),
        )
        for stage in TIMED_STAGES
    ]


def time_to_hire_days(h: AppHistory) -> float | None:
    hired = [e for e in h.events if e.to_stage is S.HIRED]
    if hired:
        return float(_days(h.created_at, hired[-1].at))
    if h.stage is S.HIRED and h.decided_at is not None:
        return float(_days(h.created_at, h.decided_at))
    return None


def kpis(histories: list[AppHistory]) -> CohortKpis:
    hired = [h for h in histories if _reached_rank(h) == _rank(S.HIRED)]
    times = [t for t in map(time_to_hire_days, hired) if t is not None]
    return CohortKpis(
        applications=len(histories),
        reached_interview=sum(1 for h in histories if _reached_rank(h) >= _rank(S.INTERVIEW)),
        hires=len(hired),
        median_time_to_hire_days=float(median(times)) if len(times) >= MIN_N else None,
        hires_n=len(times),
    )


def source_rows(histories: list[AppHistory]) -> list[SourceRow]:
    grouped: dict[str, list[AppHistory]] = defaultdict(list)
    for h in histories:
        grouped[h.source or "direct"].append(h)
    rows = [
        SourceRow(
            source=source,
            applications=len(group),
            reached_interview=sum(1 for h in group if _reached_rank(h) >= _rank(S.INTERVIEW)),
            hires=sum(1 for h in group if _reached_rank(h) == _rank(S.HIRED)),
        )
        for source, group in grouped.items()
    ]
    return sorted(rows, key=lambda row: (-row.applications, row.source))


def _label(stage: ApplicationStage, *, step: bool = False) -> str:
    """Stage name for copy. The funnel calls the first step "Applied"; time in
    stage names the stage itself."""
    return "Applied" if step and stage is S.NEW else stage.value.capitalize()


def diagnosis(steps: list[FunnelStep], times: list[StageTime], cohort_size: int) -> list[str]:
    if cohort_size < MIN_COHORT:
        return [f"Not enough data yet ({cohort_size} applications)"]
    lines: list[str] = []
    # the step the most candidates left from; the last step has no next
    best: int | None = None
    for i, step in enumerate(steps[:-1]):
        left = step.rejected_from + step.withdrawn_from
        if left > 0 and (
            best is None or left > steps[best].rejected_from + steps[best].withdrawn_from
        ):
            best = i
    if best is not None and steps[best].pass_through is not None:
        pct = round(steps[best].pass_through or 0)
        lines.append(
            f"Most candidates leave between {_label(steps[best].stage, step=True)} and "
            f"{_label(steps[best + 1].stage, step=True)}: {pct} percent move on."
        )
    slowest: StageTime | None = None
    for t in times:
        if t.median_days is not None and t.n >= MIN_N:
            if slowest is None or (slowest.median_days or 0) < t.median_days:
                slowest = t
    if slowest is not None:
        lines.append(
            f"Candidates wait longest in {_label(slowest.stage)}: "
            f"median {slowest.median_days:g} days (n = {slowest.n})."
        )
    return lines


def period_bounds(
    period: Period, now: datetime
) -> tuple[datetime | None, datetime, tuple[datetime, datetime] | None]:
    """(start, end, previous). Start is the first UTC calendar day of a "last N
    days" window (today and the N-1 days before it) and is inclusive; the
    previous window is the N days before it and ends where the current begins."""
    if period == "all":
        return None, now, None
    days = PERIOD_DAYS[period]
    today = datetime.combine(now.astimezone(UTC).date(), datetime.min.time(), UTC)
    start = today - timedelta(days=days - 1)
    return start, now, (start - timedelta(days=days), start)


def _cohort_where(
    company: Company,
    job_id: uuid.UUID | None,
    start: datetime | None,
    end: datetime,
    *,
    end_inclusive: bool,
) -> list[ColumnElement[bool]]:
    conditions: list[ColumnElement[bool]] = [Application.company_id == company.id]
    if job_id is not None:
        conditions.append(Application.job_id == job_id)
    if start is not None:
        conditions.append(Application.created_at >= start)
    conditions.append(
        Application.created_at <= end if end_inclusive else Application.created_at < end
    )
    return conditions


def _parse_stage(value: object) -> ApplicationStage | None:
    try:
        return ApplicationStage(str(value))
    except ValueError:
        return None


async def _histories(
    db: AsyncSession,
    conditions: list[ColumnElement[bool]],
) -> list[AppHistory]:
    """The cohort with its stage.changed rows: two queries, rows ordered by
    application then time. A row without a readable `to` is dropped."""
    apps = (
        await db.execute(
            select(
                Application.id,
                Application.created_at,
                Application.stage,
                Application.stage_changed_at,
                Application.decided_at,
                Application.source,
            ).where(*conditions)
        )
    ).all()
    events: dict[uuid.UUID, list[StageEvent]] = defaultdict(list)
    rows = await db.execute(
        select(ActivityLog.application_id, ActivityLog.created_at, ActivityLog.payload)
        .join(Application, Application.id == ActivityLog.application_id)
        .where(ActivityLog.type == STAGE_CHANGED, *conditions)
        .order_by(ActivityLog.application_id, ActivityLog.created_at)
    )
    for application_id, created_at, payload in rows.all():
        to_stage = _parse_stage(payload.get("to"))
        if application_id is None or to_stage is None:
            continue
        events[application_id].append(
            StageEvent(
                at=created_at, from_stage=_parse_stage(payload.get("from")), to_stage=to_stage
            )
        )
    return [
        AppHistory(
            id=app_id,
            created_at=created_at,
            stage=stage,
            stage_changed_at=stage_changed_at,
            decided_at=decided_at,
            source=source,
            events=tuple(events.get(app_id, ())),
        )
        for app_id, created_at, stage, stage_changed_at, decided_at, source in apps
    ]


async def _quiz_line(
    db: AsyncSession, conditions: list[ColumnElement[bool]], now: datetime
) -> QuizLine:
    # the column flips to expired only when a candidate opens a dead link, so a
    # pending invite past its window counts as expired too (as timeline.py does)
    lapsed = (QuizAttempt.status == AttemptStatus.EXPIRED) | (
        (QuizAttempt.status == AttemptStatus.PENDING) & (QuizAttempt.expires_at < now)
    )
    row = (
        await db.execute(
            select(
                func.count(),
                func.count().filter(QuizAttempt.status == AttemptStatus.COMPLETED),
                func.count().filter(lapsed),
            )
            .join(Application, Application.id == QuizAttempt.application_id)
            .where(QuizAttempt.status != AttemptStatus.INVALIDATED, *conditions)
        )
    ).one()
    return QuizLine(invited=row[0], completed=row[1], expired=row[2])


async def reports(
    db: AsyncSession,
    company: Company,
    *,
    period: Period,
    job_id: uuid.UUID | None,
    now: datetime | None = None,
) -> ReportsOut:
    now = now or datetime.now(UTC)
    start, end, previous_bounds = period_bounds(period, now)
    conditions = _cohort_where(company, job_id, start, end, end_inclusive=True)
    cohort = await _histories(db, conditions)
    previous = None
    if previous_bounds is not None:
        previous_conditions = _cohort_where(
            company, job_id, previous_bounds[0], previous_bounds[1], end_inclusive=False
        )
        previous = kpis(await _histories(db, previous_conditions))
    steps = funnel(cohort)
    times = time_in_stage(cohort, now)
    return ReportsOut(
        period=period,
        job_id=job_id,
        cohort=kpis(cohort),
        previous=previous,
        funnel=steps,
        quiz=await _quiz_line(db, conditions, now),
        time_in_stage=times,
        sources=source_rows(cohort),
        diagnosis=diagnosis(steps, times, len(cohort)),
        quiz_scores=await _quiz_counts(db, company, job_id=job_id, since=start),
        weekly=await _weekly(db, company, job_id=job_id, since=start, weeks=PERIOD_WEEKS[period]),
    )
