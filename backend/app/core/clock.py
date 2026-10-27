"""One notion of "today" for everything bucketed by UTC calendar day: the
job view counters and the 30-day stats windows (spec job posts v2 5.5)."""

from datetime import UTC, date, datetime


def utc_today() -> date:
    return datetime.now(UTC).date()
