"""Access-log hygiene (GDPR G4).

Uvicorn's default access log writes the full request path; candidate
capability tokens (quiz/status/interview/invite) are path segments and
short-lived OAuth values ride as query params on the Google flow. Scrub
them so logs keep client IP + route shape (security logging) without
live bearer tokens next to the IPs that used them.
"""

import logging
import re

_TOKEN_PATH = re.compile(r"(/public/(?:quiz|applications|interviews|invites)/)[^/?\s]+")
_TOKEN_QUERY = re.compile(r"([?&](?:gs|code|state|token)=)[^&\s]+")


def scrub_path(path: str) -> str:
    path = _TOKEN_PATH.sub(r"\1[token]", path)
    return _TOKEN_QUERY.sub(r"\1[token]", path)


class AccessLogScrubber(logging.Filter):
    """Rewrites the request-path arg of uvicorn.access records.

    Uvicorn logs access lines as
    ``'%s - "%s %s HTTP/%s" %d' % (addr, method, path, http, status)`` —
    the path is ``args[2]``. Anything else passes through untouched.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        args = record.args
        if isinstance(args, tuple) and len(args) == 5 and isinstance(args[2], str):
            record.args = (*args[:2], scrub_path(args[2]), *args[3:])
        return True


def install_access_log_scrubber() -> None:
    logger = logging.getLogger("uvicorn.access")
    if not any(isinstance(f, AccessLogScrubber) for f in logger.filters):
        logger.addFilter(AccessLogScrubber())
