"""GDPR G4: capability tokens must not reach uvicorn's access log."""

import logging

from app.core.logcfg import AccessLogScrubber, install_access_log_scrubber, scrub_path

TOKEN = "IjI2ZjQwMzgwIg.aJx1uA.decoy-signature"


def _record(path: str) -> logging.LogRecord:
    """A record shaped like uvicorn.access emits them."""
    return logging.LogRecord(
        name="uvicorn.access",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg='%s - "%s %s HTTP/%s" %d',
        args=("203.0.113.9:51234", "GET", path, "1.1", 200),
        exc_info=None,
    )


def test_scrubs_all_public_token_routes() -> None:
    for route in ("quiz", "applications", "interviews", "invites"):
        assert scrub_path(f"/api/v1/public/{route}/{TOKEN}") == f"/api/v1/public/{route}/[token]"


def test_keeps_subpath_after_token() -> None:
    assert scrub_path(f"/api/v1/public/quiz/{TOKEN}/state") == "/api/v1/public/quiz/[token]/state"
    assert (
        scrub_path(f"/api/v1/public/applications/{TOKEN}/request-data")
        == "/api/v1/public/applications/[token]/request-data"
    )


def test_scrubs_token_query_params() -> None:
    assert scrub_path("/setup?gs=" + TOKEN) == "/setup?gs=[token]"
    assert (
        scrub_path("/api/v1/auth/google/callback?code=4/abc&state=xyz")
        == "/api/v1/auth/google/callback?code=[token]&state=[token]"
    )


def test_leaves_normal_paths_alone() -> None:
    for path in ("/api/v1/jobs", "/api/v1/public/companies/acme/jobs", "/api/health"):
        assert scrub_path(path) == path


def test_filter_rewrites_path_and_keeps_client_ip() -> None:
    record = _record(f"/api/v1/public/quiz/{TOKEN}/state")
    assert AccessLogScrubber().filter(record) is True
    line = record.getMessage()
    assert TOKEN not in line
    assert "[token]/state" in line
    assert "203.0.113.9:51234" in line
    assert "200" in line


def test_filter_ignores_foreign_record_shapes() -> None:
    record = logging.LogRecord(
        name="uvicorn.error",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="plain message %s",
        args=("arg",),
        exc_info=None,
    )
    assert AccessLogScrubber().filter(record) is True
    assert record.getMessage() == "plain message arg"


def test_install_is_idempotent() -> None:
    install_access_log_scrubber()
    install_access_log_scrubber()
    scrubbers = [
        f for f in logging.getLogger("uvicorn.access").filters if isinstance(f, AccessLogScrubber)
    ]
    assert len(scrubbers) == 1
