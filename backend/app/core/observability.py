"""Optional Sentry error reporting (board card A1 "Observability").

Off unless GANEK_SENTRY_DSN is set: the SDK is imported lazily inside
init_sentry, so an unset DSN means no import side effects and no outbound
traffic at all. When on, the SDK's default PII collection stays off and
before_send scrubs every string in the event (emails, capability tokens in
paths and query strings, CV file names), drops cookies and auth headers,
and the request id is a tag so a Sentry issue maps to a log line. The tag
is set from inside the request (tag_request): the SDK's ASGI wrapper sits
outside our middleware, so the contextvar is already reset by the time an
unhandled exception is captured.
"""

import logging
import re
from typing import TYPE_CHECKING, Any, cast

from app.core.config import settings
from app.core.logcfg import request_id_var, scrub_path

if TYPE_CHECKING:
    from sentry_sdk._types import Event

logger = logging.getLogger(__name__)

_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_PDF_NAME = re.compile(r"[^\s\"'<>]+\.pdf\b", re.IGNORECASE)
# itsdangerous-style capability tokens (payload.timestamp.signature) wherever
# they appear, not only in URL positions; over-scrubbing is the safe side
_SIGNED_TOKEN = re.compile(r"\b[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{4,}\.[A-Za-z0-9_-]{12,}\b")
_DROPPED_KEYS = {"cookie", "cookies", "authorization", "set-cookie", "x-forwarded-for"}
_enabled = False


def scrub_text(value: str) -> str:
    value = scrub_path(value)
    value = _SIGNED_TOKEN.sub("[token]", value)
    return _PDF_NAME.sub("[cv]", _EMAIL.sub("[email]", value))


def scrub_event(event: dict[str, Any]) -> dict[str, Any]:
    """Recursive scrub of a Sentry event payload (pure, testable)."""

    def walk(node: Any) -> Any:
        if isinstance(node, str):
            return scrub_text(node)
        if isinstance(node, dict):
            return {
                key: "[redacted]" if str(key).lower() in _DROPPED_KEYS else walk(value)
                for key, value in node.items()
            }
        if isinstance(node, list):
            return [walk(item) for item in node]
        return node

    scrubbed: dict[str, Any] = walk(event)
    request_id = request_id_var.get()
    if request_id:
        scrubbed.setdefault("tags", {})["request_id"] = request_id
    return scrubbed


def _before_send(event: "Event", _hint: dict[str, Any]) -> "Event | None":
    return cast("Event", scrub_event(dict(event)))


def tag_request(request_id: str) -> None:
    """Attach the request id to whatever the SDK captures for this request."""
    if not _enabled:
        return
    import sentry_sdk

    sentry_sdk.set_tag("request_id", request_id)


def init_sentry(*, dsn: str | None, component: str, transport: Any = None) -> bool:
    """Initialise the SDK when a DSN is configured. Returns whether it did.
    ``transport`` is for tests (capture instead of HTTP)."""
    global _enabled
    if not dsn:
        return False
    import sentry_sdk
    from sentry_sdk.integrations.fastapi import FastApiIntegration
    from sentry_sdk.integrations.logging import LoggingIntegration
    from sentry_sdk.integrations.starlette import StarletteIntegration

    sentry_sdk.init(
        dsn=dsn,
        environment=settings.sentry_environment,
        release=f"ganek@{settings.version}",
        # default PII collection stays at the SDK default (off); no
        # send_default_pii kwarg because 2.7x deprecates it
        traces_sample_rate=settings.sentry_traces_sample_rate,
        before_send=_before_send,
        integrations=[
            StarletteIntegration(transaction_style="endpoint"),
            FastApiIntegration(transaction_style="endpoint"),
            # breadcrumbs from INFO, events only from ERROR (unhandled
            # exceptions arrive via the ASGI integrations anyway)
            LoggingIntegration(level=logging.INFO, event_level=logging.ERROR),
        ],
        transport=transport,
    )
    sentry_sdk.set_tag("component", component)
    _enabled = True
    logger.info("sentry error reporting enabled (%s)", component)
    return True
