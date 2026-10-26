"""Where an application came from (spec job posts v2 5.4, decision JP2).

One string column, one grammar, mirrored by the frontend resolver that
produces the values (``frontend/src/lib/source.ts``). The backend only
validates: an odd value becomes NULL and never blocks an application.

- ``direct``
- a known bucket: google, linkedin, indeed, facebook, x, glassdoor, xing,
  stepstone, hn, reddit, github, website
- ``link:<name>`` for a tracked link or utm_source, name ``[a-z0-9_-]{1,40}``
- ``ref:<host>`` for an unknown referrer, host a lower-case registrable
  domain with at least one dot, max 63 chars, never a path or query
"""

import re

KNOWN_SOURCES: frozenset[str] = frozenset(
    {
        "direct",
        "google",
        "linkedin",
        "indeed",
        "facebook",
        "x",
        "glassdoor",
        "xing",
        "stepstone",
        "hn",
        "reddit",
        "github",
        "website",
    }
)

MAX_LENGTH = 100  # the column width

_LINK = re.compile(r"^link:[a-z0-9_-]{1,40}$")
_REF = re.compile(r"^ref:(?=.{1,63}$)[a-z0-9-]+(?:\.[a-z0-9-]+)+$")


def normalize_source(value: str | None) -> str | None:
    """The stored form of a submitted source, or None when it is not one."""
    if value is None:
        return None
    candidate = value.strip().lower()
    if not candidate or len(candidate) > MAX_LENGTH:
        return None
    if candidate in KNOWN_SOURCES or _LINK.match(candidate) or _REF.match(candidate):
        return candidate
    return None
