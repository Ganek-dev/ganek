"""Pipeline signals: the workspace stage limit (stalled-candidate cue).

Only the setting reader lives here so far; the signal queries build on it.
"""

from app.models.company import Company

STAGE_LIMIT_KEY = "stage_limit_days"
DEFAULT_STAGE_LIMIT_DAYS = 7


def stage_limit(company: Company) -> int:
    """Days a live application may sit in one stage before it is flagged."""
    return int((company.settings or {}).get(STAGE_LIMIT_KEY, DEFAULT_STAGE_LIMIT_DAYS))
