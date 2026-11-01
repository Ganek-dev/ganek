"""Reports pure core: funnel, left-from, time in stage, time to hire, diagnosis,
period bounds. Histories are built by hand, `now` is fixed."""

import uuid
from datetime import UTC, datetime, timedelta

from app.models import ApplicationStage as S
from app.schemas.stats import FunnelStep, StageTime
from app.services import reports as r

NOW = datetime(2026, 11, 10, 12, 0, tzinfo=UTC)


def at(days_ago: int, hour: int = 12) -> datetime:
    return (NOW - timedelta(days=days_ago)).replace(hour=hour)


def ev(days_ago: int, from_stage: S | None, to_stage: S) -> r.StageEvent:
    return r.StageEvent(at=at(days_ago), from_stage=from_stage, to_stage=to_stage)


def hist(
    stage: S = S.NEW,
    *events: r.StageEvent,
    created: int = 30,
    changed: int | None = None,
    decided: datetime | None = None,
    source: str | None = None,
) -> r.AppHistory:
    return r.AppHistory(
        id=uuid.uuid4(),
        created_at=at(created),
        stage=stage,
        stage_changed_at=at(created if changed is None else changed),
        decided_at=decided,
        source=source,
        events=tuple(events),
    )


def step(steps: list[FunnelStep], stage: S) -> FunnelStep:
    return next(s for s in steps if s.stage is stage)


def test_reached_counts_skipped_stage() -> None:
    h = hist(S.INTERVIEW, ev(10, S.NEW, S.INTERVIEW))
    assert r.reached_stage(h) is S.INTERVIEW
    steps = r.funnel([h])
    assert [s.reached for s in steps] == [1, 1, 1, 0, 0]


def test_reached_is_highest_ever_after_move_back() -> None:
    h = hist(S.SCREENING, ev(20, S.NEW, S.OFFER), ev(10, S.OFFER, S.SCREENING))
    assert r.reached_stage(h) is S.OFFER
    steps = r.funnel([h])
    assert step(steps, S.OFFER).reached == 1
    assert step(steps, S.SCREENING).still_here == 1
    assert step(steps, S.OFFER).still_here == 0


def test_reached_floor_is_new_when_only_outcomes() -> None:
    h = hist(S.REJECTED, ev(5, S.NEW, S.REJECTED))
    assert r.reached_stage(h) is S.NEW


def test_left_from_uses_latest_rejection() -> None:
    h = hist(
        S.REJECTED,
        ev(20, S.NEW, S.SCREENING),
        ev(18, S.SCREENING, S.REJECTED),
        ev(15, S.REJECTED, S.INTERVIEW),
        ev(5, S.INTERVIEW, S.REJECTED),
    )
    assert r.left_from(h) == (S.REJECTED, S.INTERVIEW)


def test_left_from_walks_back_past_a_held_rejection_withdrawal() -> None:
    h = hist(S.WITHDRAWN, ev(9, S.INTERVIEW, S.REJECTED), ev(8, S.REJECTED, S.WITHDRAWN))
    assert r.left_from(h) == (S.WITHDRAWN, S.INTERVIEW)


def test_left_from_none_when_no_earlier_funnel_stage() -> None:
    h = hist(S.WITHDRAWN, ev(8, S.REJECTED, S.WITHDRAWN))
    assert r.left_from(h) is None
    steps = r.funnel([h])
    assert sum(s.rejected_from + s.withdrawn_from for s in steps) == 0


def test_reopened_rejection_counts_nowhere_as_left() -> None:
    h = hist(S.SCREENING, ev(9, S.SCREENING, S.REJECTED), ev(8, S.REJECTED, S.SCREENING))
    assert r.left_from(h) is None
    assert all(s.rejected_from == 0 for s in r.funnel([h]))


def test_rejected_and_withdrawn_from_counted_per_step() -> None:
    rejected = hist(S.REJECTED, ev(9, S.NEW, S.SCREENING), ev(8, S.SCREENING, S.REJECTED))
    withdrawn = hist(S.WITHDRAWN, ev(9, S.NEW, S.WITHDRAWN))
    steps = r.funnel([rejected, withdrawn])
    assert step(steps, S.SCREENING).rejected_from == 1
    assert step(steps, S.NEW).withdrawn_from == 1
    assert step(steps, S.NEW).still_here == 0


def test_pass_through_none_when_nothing_reached() -> None:
    steps = r.funnel([hist(S.NEW)])
    assert step(steps, S.NEW).pass_through == 0.0
    assert step(steps, S.SCREENING).pass_through is None  # nobody reached screening
    assert step(steps, S.HIRED).pass_through is None  # last step has no next
    assert r.funnel([])[0].pass_through is None


def test_pass_through_is_percent_of_next_over_this() -> None:
    hs = [hist(S.SCREENING, ev(5, S.NEW, S.SCREENING)), hist(S.NEW), hist(S.NEW)]
    assert step(r.funnel(hs), S.NEW).pass_through == 33.3


def test_still_here_is_live_at_stage() -> None:
    hs = [
        hist(S.INTERVIEW, ev(5, S.NEW, S.INTERVIEW)),
        hist(S.HIRED, ev(5, S.NEW, S.HIRED)),
        hist(S.REJECTED, ev(5, S.NEW, S.INTERVIEW), ev(4, S.INTERVIEW, S.REJECTED)),
    ]
    steps = r.funnel(hs)
    assert step(steps, S.INTERVIEW).still_here == 1
    assert step(steps, S.HIRED).still_here == 0
    assert step(steps, S.INTERVIEW).reached == 3


def test_time_in_stage_ignores_live_stay_and_uses_created_at_for_new() -> None:
    h = hist(
        S.INTERVIEW,
        ev(26, S.NEW, S.SCREENING),  # new: created 30 days ago -> 4 days
        ev(20, S.SCREENING, S.INTERVIEW),  # screening: 6 days
        created=30,
        changed=20,
    )
    times = {t.stage: t for t in r.time_in_stage([h], NOW)}
    assert times[S.NEW].n == 1 and times[S.NEW].median_days is None
    assert times[S.SCREENING].n == 1
    assert times[S.INTERVIEW].n == 0  # the live stay is not a completed stay
    assert times[S.INTERVIEW].oldest_live_days == 20
    assert times[S.NEW].oldest_live_days is None
    assert [t.stage for t in r.time_in_stage([h], NOW)] == [
        S.NEW,
        S.SCREENING,
        S.INTERVIEW,
        S.OFFER,
    ]


def test_time_in_stage_is_utc_calendar_days_not_24h() -> None:
    late = r.StageEvent(
        at=datetime(2026, 11, 2, 0, 5, tzinfo=UTC), from_stage=S.NEW, to_stage=S.SCREENING
    )
    h = r.AppHistory(
        id=uuid.uuid4(),
        created_at=datetime(2026, 11, 1, 23, 55, tzinfo=UTC),
        stage=S.SCREENING,
        stage_changed_at=late.at,
        decided_at=None,
        source=None,
        events=(late,),
    )
    # ten minutes apart but across midnight: one calendar day
    assert r.completed_stays(h) == [(S.NEW, 1)]


def test_time_in_stage_skips_stay_with_unknown_entry() -> None:
    h = hist(S.REJECTED, ev(5, S.INTERVIEW, S.REJECTED))  # earlier rows missing
    assert r.completed_stays(h) == []


def test_time_in_stage_counts_each_visit_after_a_move_back() -> None:
    h = hist(
        S.SCREENING,
        ev(20, S.NEW, S.SCREENING),
        ev(15, S.SCREENING, S.NEW),
        ev(10, S.NEW, S.SCREENING),
    )
    assert [stage for stage, _ in r.completed_stays(h)] == [S.NEW, S.SCREENING, S.NEW]


def test_median_rules_below_three() -> None:
    def moved(days: int) -> r.AppHistory:
        return hist(S.SCREENING, ev(30 - days, S.NEW, S.SCREENING), created=30, changed=0)

    two = {t.stage: t for t in r.time_in_stage([moved(2), moved(4)], NOW)}
    assert two[S.NEW].n == 2 and two[S.NEW].median_days is None
    three = {t.stage: t for t in r.time_in_stage([moved(2), moved(4), moved(10)], NOW)}
    assert three[S.NEW].n == 3 and three[S.NEW].median_days == 4.0
    four = {t.stage: t for t in r.time_in_stage([moved(2), moved(4), moved(10), moved(20)], NOW)}
    assert four[S.NEW].median_days == 7.0


def test_time_to_hire_from_history_and_decided_at_fallback() -> None:
    from_history = hist(S.HIRED, ev(20, S.OFFER, S.HIRED), created=30, decided=at(1))
    assert r.time_to_hire_days(from_history) == 10.0
    latest = hist(
        S.HIRED, ev(20, S.OFFER, S.HIRED), ev(15, S.HIRED, S.OFFER), ev(12, S.OFFER, S.HIRED)
    )
    assert r.time_to_hire_days(latest) == 18.0
    fallback = hist(S.HIRED, created=30, decided=at(5))
    assert r.time_to_hire_days(fallback) == 25.0
    assert r.time_to_hire_days(hist(S.HIRED, created=30)) is None
    assert r.time_to_hire_days(hist(S.OFFER, created=30, decided=at(5))) is None


def test_kpis_counts_and_hire_median_rules() -> None:
    def hired(days: int) -> r.AppHistory:
        return hist(S.HIRED, ev(30 - days, S.OFFER, S.HIRED), created=30)

    two = r.kpis([hired(10), hired(20), hist(S.NEW)])
    assert (two.applications, two.hires, two.hires_n) == (3, 2, 2)
    assert two.median_time_to_hire_days is None
    three = r.kpis([hired(10), hired(20), hired(30), hist(S.INTERVIEW, ev(5, S.NEW, S.INTERVIEW))])
    assert three.median_time_to_hire_days == 20.0
    assert three.reached_interview == 4
    assert three.hires == 3


def _steps(left: list[int], pass_through: list[float | None]) -> list[FunnelStep]:
    stages = [S.NEW, S.SCREENING, S.INTERVIEW, S.OFFER, S.HIRED]
    return [
        FunnelStep(
            stage=stage,
            reached=100,
            pass_through=pass_through[i],
            rejected_from=left[i],
            withdrawn_from=0,
            still_here=0,
        )
        for i, stage in enumerate(stages)
    ]


def _times(*rows: tuple[S, float | None, int]) -> list[StageTime]:
    return [StageTime(stage=s, median_days=m, n=n, oldest_live_days=None) for s, m, n in rows]


def test_diagnosis_names_largest_left_not_lowest_pass_through() -> None:
    steps = _steps([3, 47, 19, 2, 0], [90.0, 55.0, 19.0, 80.0, None])
    lines = r.diagnosis(steps, [], 100)
    assert lines == ["Most candidates leave between Screening and Interview: 55 percent move on."]


def test_diagnosis_tie_goes_earlier_and_omitted_when_nobody_left() -> None:
    steps = _steps([0, 5, 5, 0, 0], [90.0, 50.0, 40.0, 80.0, None])
    assert r.diagnosis(steps, [], 50)[0].startswith("Most candidates leave between Screening")
    assert r.diagnosis(_steps([0, 0, 0, 0, 0], [90.0, 50.0, 40.0, 80.0, None]), [], 50) == []


def test_diagnosis_last_step_has_no_next_so_never_named() -> None:
    steps = _steps([0, 0, 0, 0, 9], [90.0, 50.0, 40.0, 80.0, None])
    assert r.diagnosis(steps, [], 50) == []


def test_diagnosis_slowest_stage_needs_n_three() -> None:
    steps = _steps([0, 0, 0, 0, 0], [None] * 5)
    times = _times(
        (S.NEW, 2.0, 5), (S.SCREENING, None, 2), (S.INTERVIEW, 6.5, 4), (S.OFFER, 3.0, 3)
    )
    assert r.diagnosis(steps, times, 20) == [
        "Candidates wait longest in Interview: median 6.5 days (n = 4)."
    ]
    whole = _times((S.NEW, 4.0, 5), (S.SCREENING, 4.0, 5))
    assert r.diagnosis(steps, whole, 20) == [
        "Candidates wait longest in New: median 4 days (n = 5)."
    ]


def test_diagnosis_below_ten() -> None:
    steps = _steps([9, 0, 0, 0, 0], [50.0, None, None, None, None])
    assert r.diagnosis(steps, [], 9) == ["Not enough data yet (9 applications)"]
    assert r.diagnosis(steps, [], 10)[0].startswith("Most candidates leave")


def test_period_bounds_calendar_days_and_all() -> None:
    start, end, previous = r.period_bounds("30d", NOW)
    assert start == datetime(2026, 10, 12, tzinfo=UTC)  # today and the 29 days before
    assert end == NOW
    assert previous == (datetime(2026, 9, 12, tzinfo=UTC), start)
    assert r.period_bounds("90d", NOW)[0] == datetime(2026, 8, 13, tzinfo=UTC)
    assert r.period_bounds("12m", NOW)[0] == datetime(2025, 11, 11, tzinfo=UTC)
    assert r.period_bounds("all", NOW) == (None, NOW, None)


def test_source_label_direct_for_null() -> None:
    hs = [
        hist(S.NEW, source=None),
        hist(S.HIRED, ev(2, S.OFFER, S.HIRED), source="linkedin"),
        hist(S.NEW, source="linkedin"),
        hist(S.INTERVIEW, ev(2, S.NEW, S.INTERVIEW), source=None),
    ]
    rows = r.source_rows(hs)
    assert [(x.source, x.applications, x.reached_interview, x.hires) for x in rows] == [
        ("direct", 2, 1, 0),
        ("linkedin", 2, 1, 1),
    ]
