"""Optional Sentry: off means off; on means scrubbed events with the
request id."""

from typing import Any

import pytest
import sentry_sdk
from httpx import AsyncClient
from sentry_sdk.envelope import Envelope
from sentry_sdk.transport import Transport

from app.core import observability
from app.core.config import settings
from app.core.logcfg import request_id_var
from app.main import app

TOKEN = "IjI2ZjQwMzgwIg.aJx1uA.decoy-signature"


class CaptureTransport(Transport):
    envelopes: list[Envelope] = []

    def capture_envelope(self, envelope: Envelope) -> None:
        CaptureTransport.envelopes.append(envelope)

    def flush(self, timeout: float, callback: Any = None) -> None:
        return None

    def kill(self) -> None:
        return None


@app.get("/api/_test/boom", include_in_schema=False)
async def _boom() -> None:
    raise RuntimeError(f"failed for jane.doe@example.com with cv resume-final.pdf {TOKEN}")


def test_unset_dsn_initialises_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    def forbidden(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("sentry_sdk.init must not be called without a DSN")

    monkeypatch.setattr(sentry_sdk, "init", forbidden)
    assert observability.init_sentry(dsn=None, component="backend") is False
    assert observability.init_sentry(dsn="", component="worker") is False
    # the test settings never set a DSN, so the imported app did not init either
    assert settings.sentry_dsn is None


def test_scrub_event_strips_pii_and_tags_request_id() -> None:
    token = request_id_var.set("req-7")
    try:
        event = observability.scrub_event(
            {
                "message": (
                    "candidate ann@acme.dev uploaded Ann_CV.pdf via "
                    f"/api/v1/public/quiz/{TOKEN}/state"
                ),
                "request": {
                    "url": f"http://x/api/v1/auth/google/callback?code=abc&state={TOKEN}",
                    "headers": {"Cookie": "ganek_session=secret", "Accept": "*/*"},
                    "cookies": {"ganek_session": "secret"},
                },
                "exception": {"values": [{"value": "mail bob@example.org bounced"}]},
            }
        )
    finally:
        request_id_var.reset(token)
    assert (
        event["message"] == "candidate [email] uploaded [cv] via /api/v1/public/quiz/[token]/state"
    )
    assert event["request"]["url"].endswith("?code=[token]&state=[token]")
    assert event["request"]["headers"] == {"Cookie": "[redacted]", "Accept": "*/*"}
    assert event["request"]["cookies"] == "[redacted]"
    assert event["exception"]["values"][0]["value"] == "mail [email] bounced"
    assert event["tags"] == {"request_id": "req-7"}


async def test_unhandled_exception_reaches_sentry_scrubbed(client: AsyncClient) -> None:
    CaptureTransport.envelopes = []
    assert observability.init_sentry(
        dsn="https://public@sentry.invalid/1", component="backend", transport=CaptureTransport
    )
    try:
        with pytest.raises(RuntimeError):
            await client.get("/api/_test/boom", headers={"X-Request-ID": "trace-boom"})
        sentry_sdk.flush()
        events = [
            item.payload.json
            for env in CaptureTransport.envelopes
            for item in env.items
            if item.type == "event"
        ]
        assert events, "no event captured"
        event = events[-1]
        assert event["tags"]["request_id"] == "trace-boom"
        flat = str(event)
        assert "jane.doe@example.com" not in flat
        assert "resume-final.pdf" not in flat
        assert TOKEN not in flat
        assert "[email]" in flat and "[cv]" in flat
    finally:
        # back to "off" so later tests see no client
        sentry_sdk.get_client().close()
