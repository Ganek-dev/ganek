"""The decision date a candidate is promised on the status page.

A company sets its decision window in days (``decision_window_days``,
Hiring settings; default 14). Every application inherits applied + window
unless the team set a date on that application (``decision_expected_on``).
Dates, not timestamps: a promise is a day, and a day must not shift with
the reader's time zone.
"""

from datetime import UTC, date, timedelta

from app.models import Application, Company

SETTINGS_KEY = "decision_window_days"
DEFAULT_WINDOW_DAYS = 14
MIN_WINDOW_DAYS = 1
MAX_WINDOW_DAYS = 90
# a per-application date may sit at most this far after the application
MAX_OVERRIDE_DAYS = 365


def window_days(company: Company) -> int:
    """The company's decision window; a missing or out-of-range value
    falls back to the default."""
    raw = (company.settings or {}).get(SETTINGS_KEY)
    if isinstance(raw, bool) or not isinstance(raw, int):
        return DEFAULT_WINDOW_DAYS
    if raw < MIN_WINDOW_DAYS or raw > MAX_WINDOW_DAYS:
        return DEFAULT_WINDOW_DAYS
    return raw


def applied_on(application: Application) -> date:
    return application.created_at.astimezone(UTC).date()


def default_decision_date(application: Application, company: Company) -> date:
    return applied_on(application) + timedelta(days=window_days(company))


def decision_expected_on(application: Application, company: Company) -> date:
    """The date the status page shows: the team's own date when set,
    otherwise applied + the company window."""
    if application.decision_expected_on is not None:
        return application.decision_expected_on
    return default_decision_date(application, company)


def override_problem(application: Application, value: date) -> str | None:
    """Why a per-application date is refused, or None when it is fine."""
    start = applied_on(application)
    if value < start:
        return "The decision date cannot be before the application date"
    if value > start + timedelta(days=MAX_OVERRIDE_DAYS):
        return "The decision date must be within a year of the application"
    return None
