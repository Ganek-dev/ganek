"""Request ids: echoed header, honoured inbound ids, stamped on log records,
and the JSON formatter."""

import json
import logging
from collections.abc import Iterator

import pytest
from httpx import AsyncClient

from app.core import logcfg
from app.core.requestid import resolve_request_id
from app.main import app

probe_logger = logging.getLogger("app.tests.request_id_probe")


@app.get("/api/_test/log-probe", include_in_schema=False)
async def _log_probe() -> dict[str, str]:
    probe_logger.info("probe inside request")
    return {"ok": "yes"}


class Capture(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.records: list[logging.LogRecord] = []
        self.addFilter(logcfg.RequestIdFilter())

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


@pytest.fixture
def capture() -> Iterator[Capture]:
    handler = Capture()
    probe_logger.addHandler(handler)
    probe_logger.setLevel(logging.INFO)
    try:
        yield handler
    finally:
        probe_logger.removeHandler(handler)


async def test_response_carries_a_generated_request_id(client: AsyncClient) -> None:
    resp = await client.get("/api/health")
    assert resp.status_code == 200
    rid = resp.headers["x-request-id"]
    assert len(rid) == 32 and all(c in "0123456789abcdef" for c in rid)


async def test_inbound_request_id_is_honoured(client: AsyncClient) -> None:
    resp = await client.get("/api/health", headers={"X-Request-ID": "proxy-abc.123"})
    assert resp.headers["x-request-id"] == "proxy-abc.123"


async def test_garbage_inbound_id_is_replaced(client: AsyncClient) -> None:
    resp = await client.get("/api/health", headers={"X-Request-ID": "no spaces <here>"})
    assert resp.headers["x-request-id"] != "no spaces <here>"
    assert len(resp.headers["x-request-id"]) == 32


def test_resolve_request_id_rules() -> None:
    assert resolve_request_id("ok-id_1.2") == "ok-id_1.2"
    assert resolve_request_id("x" * 65) != "x" * 65
    assert resolve_request_id(None) != resolve_request_id(None)


async def test_log_records_inside_a_request_carry_its_id(
    client: AsyncClient, capture: Capture
) -> None:
    resp = await client.get("/api/_test/log-probe", headers={"X-Request-ID": "trace-42"})
    assert resp.status_code == 200
    assert [r.request_id for r in capture.records] == ["trace-42"]  # type: ignore[attr-defined]


def test_records_outside_a_request_get_a_dash(capture: Capture) -> None:
    probe_logger.info("outside")
    assert capture.records[-1].request_id == "-"  # type: ignore[attr-defined]


def test_json_formatter_shape() -> None:
    record = logging.LogRecord(
        name="app.x",
        level=logging.WARNING,
        pathname=__file__,
        lineno=1,
        msg="hello %s",
        args=("world",),
        exc_info=None,
    )
    logcfg.RequestIdFilter().filter(record)
    line = json.loads(logcfg.JsonFormatter().format(record))
    assert line["level"] == "WARNING"
    assert line["logger"] == "app.x"
    assert line["msg"] == "hello world"
    assert line["request_id"] == "-"
    assert line["ts"].endswith("+00:00")


def test_configure_logging_is_idempotent_and_takes_over_uvicorn() -> None:
    logcfg.configure_logging(json_logs=True)
    logcfg.configure_logging(json_logs=False)
    access = logging.getLogger("uvicorn.access")
    assert access.propagate is False
    assert any(isinstance(f, logcfg.AccessLogScrubber) for f in access.filters)
    assert len(logging.getLogger().handlers) == 1
