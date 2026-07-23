from httpx import AsyncClient

from app.services.storage import sanitize_disposition_filename


async def test_security_headers_on_all_responses(client: AsyncClient) -> None:
    resp = await client.get("/api/health")
    assert resp.headers["x-content-type-options"] == "nosniff"
    assert resp.headers["x-frame-options"] == "DENY"
    assert resp.headers["referrer-policy"] == "no-referrer"
    assert resp.headers["cross-origin-opener-policy"] == "same-origin"


async def test_api_v1_responses_are_no_store(client: AsyncClient) -> None:
    resp = await client.get("/api/v1/auth/me")  # 401, but headers still apply
    assert resp.headers["cache-control"] == "no-store"


def test_disposition_filename_sanitization() -> None:
    assert sanitize_disposition_filename("jane.pdf") == "jane.pdf"
    assert (
        sanitize_disposition_filename('ev"il\r\nSet-Cookie: x=y.pdf') == "evilSet-Cookie: x=y.pdf"
    )
    assert sanitize_disposition_filename("a\\b;c.pdf") == "abc.pdf"
    assert sanitize_disposition_filename("\r\n") == "cv.pdf"
    assert len(sanitize_disposition_filename("x" * 500)) == 150
