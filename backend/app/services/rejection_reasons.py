"""The fixed list of internal rejection reasons (card "Candidate emails",
PR 2). Keys are stored on the application and in the stage.changed
payload; labels reach the CSV export and the candidate's data bundle.
The reason is internal: it never goes into an email or a candidate page."""

from typing import Literal

ReasonKey = Literal[
    "another_candidate",
    "skills_gap",
    "salary_mismatch",
    "location_or_permit",
    "no_response",
    "withdrew",
    "other",
]

REASONS: dict[str, str] = {
    "another_candidate": "Another candidate preferred",
    "skills_gap": "Skills below the bar",
    "salary_mismatch": "Salary expectations did not match",
    "location_or_permit": "Location or work permit",
    "no_response": "No response from the candidate",
    "withdrew": "Candidate withdrew",
    "other": "Other",
}

# set by the candidate's own withdrawal, never offered to a recruiter
WITHDREW = "withdrew"


def label(key: str | None) -> str:
    """The human label for a stored key; "" for none (CSV cells)."""
    if key is None:
        return ""
    return REASONS.get(key, key)
