"""Logging setup: access-log hygiene (GDPR G4), request ids, JSON output.

Uvicorn's default access log writes the full request path; candidate
capability tokens (quiz/status/interview/invite) are path segments and
short-lived OAuth values ride as query params on the Google flow. Scrub
them so logs keep client IP + route shape (security logging) without
live bearer tokens next to the IPs that used them.

Every record also carries ``request_id`` (from the contextvar the
RequestIdMiddleware sets, "-" outside a request), and ``configure_logging``
installs one stderr handler for the app, uvicorn and arq loggers in either
the human-readable text format or one JSON object per line.
"""

import json
import logging
import logging.config
import re
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Any

request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)

_TOKEN_PATH = re.compile(r"(/public/(?:quiz|applications|interviews|invites)/)[^/?\s]+")
_TOKEN_QUERY = re.compile(r"([?&](?:gs|code|state|token|preview)=)[^&\s]+")


def scrub_path(path: str) -> str:
    path = _TOKEN_PATH.sub(r"\1[token]", path)
    return _TOKEN_QUERY.sub(r"\1[token]", path)


class AccessLogScrubber(logging.Filter):
    """Rewrites the request-path arg of uvicorn.access records.

    Uvicorn logs access lines as
    ``'%s - "%s %s HTTP/%s" %d' % (addr, method, path, http, status)`` -
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


class RequestIdFilter(logging.Filter):
    """Stamps every record with the current request id ("-" outside one)."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_var.get() or "-"
        return True


class JsonFormatter(logging.Formatter):
    """One JSON object per line; no extra dependency."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "request_id": getattr(record, "request_id", "-"),
            "msg": record.getMessage(),
        }
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


TEXT_FORMAT = "%(asctime)s %(levelname)s [%(request_id)s] %(name)s: %(message)s"

# uvicorn and arq install their own handlers at process start; taking the
# loggers over (propagate off, our handler) keeps one format and one id
_TAKEN_OVER = ("uvicorn", "uvicorn.error", "uvicorn.access", "arq")


def configure_logging(*, json_logs: bool, level: str = "INFO") -> None:
    """Idempotent process-wide setup (called by the API at import and by the
    worker on startup, after arq applied its own config)."""
    logging.config.dictConfig(
        {
            "version": 1,
            "disable_existing_loggers": False,
            "filters": {"request_id": {"()": RequestIdFilter}},
            "formatters": {
                "json": {"()": JsonFormatter},
                "text": {"format": TEXT_FORMAT},
            },
            "handlers": {
                "ganek": {
                    "class": "logging.StreamHandler",
                    "stream": "ext://sys.stderr",
                    "formatter": "json" if json_logs else "text",
                    "filters": ["request_id"],
                },
            },
            "root": {"level": level.upper(), "handlers": ["ganek"]},
            "loggers": {name: {"handlers": ["ganek"], "propagate": False} for name in _TAKEN_OVER},
        }
    )
    # dictConfig replaces handlers but only ever ADDS logger filters, so the
    # scrubber goes on through the idempotent installer instead
    install_access_log_scrubber()
